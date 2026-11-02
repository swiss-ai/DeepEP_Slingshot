import unittest
from trace_format import SLOTS,CAPACITY,HEADER,WORDS,decode_record
from analyze import union
class TraceTests(unittest.TestCase):
    def test_writer_reader_offset_and_slot(self):
        self.assertEqual(HEADER,8+SLOTS);self.assertEqual(WORDS,8)
        # Model exact device writes into a sparse buffer and read with the ABI.
        block,thread,index=65,96,17;slot=block*32+thread//32
        record=[100,130,200,block,thread,12345,66,25]
        memory={8+slot:index+1}
        for j,v in enumerate(record):memory[HEADER+(slot*CAPACITY+index)*WORDS+j]=v
        decoded=decode_record([memory[HEADER+(slot*CAPACITY+index)*WORDS+j] for j in range(WORDS)],{200})
        self.assertEqual(decoded['start_ns'],100);self.assertEqual(decoded['block'],65)
        with self.assertRaises(AssertionError):decode_record([0]*WORDS,{200})
        with self.assertRaises(AssertionError):decode_record([130,100]+record[2:],{200})
    def test_overlap_is_not_added_twice(self):
        self.assertEqual(union([(0,10),(2,5),(5,15),(20,25)]),20)
        self.assertEqual(union([]),0)
if __name__=='__main__':unittest.main()
