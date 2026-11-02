| test | size B | client TX mem | server RX mem | bidir | list | align | writes | GB/s (1e9 B/s) | Mpkt/s |
|---|---:|---|---|---|---:|---:|---:|---:|---:|
| gpu-bi-s1048576 | 1048576 | GPU 0 | GPU 0 | Enabled | 256 | 64 | 86272 | 45.18 | 22.059 |
| gpu-bi-s132096 | 132096 | GPU 0 | GPU 0 | Enabled | 256 | 64 | 677888 | 44.89 | 22.086 |
| gpu-bi-s65536 | 65536 | GPU 0 | GPU 0 | Enabled | 256 | 64 | 1367808 | 44.86 | 21.903 |
| gpu-uni-s1048576 | 1048576 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 92416 | 24.19 | 11.809 |
| gpu-uni-s132096-l1 | 132096 | GPU 0 | GPU 0 | Disabled | 1 | 64 | 300412 | 9.92 | 4.882 |
| gpu-uni-s132096-l16 | 132096 | GPU 0 | GPU 0 | Disabled | 16 | 64 | 666144 | 22.00 | 10.824 |
| gpu-uni-s132096 | 132096 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 726016 | 23.97 | 11.795 |
| gpu-uni-s16384 | 16384 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 5457152 | 22.35 | 10.914 |
| gpu-uni-s262144 | 262144 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 367872 | 24.09 | 11.764 |
| gpu-uni-s65536 | 65536 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 1445632 | 23.68 | 11.564 |
| gpu-uni-s69120 | 69120 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 1371392 | 23.69 | 11.655 |
| gpu-uni-s8192-align128 | 8192 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 10114048 | 20.71 | 10.114 |
| gpu-uni-s8192-align64 | 8192 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 10082560 | 20.65 | 10.082 |
| gpu-uni-s8256-align128 | 8256 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 9995520 | 20.63 | 12.494 |
| gpu-uni-s8256-align64 | 8256 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 9984512 | 20.61 | 12.480 |
| gpu-uni-s8320-align128 | 8320 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 9946368 | 20.69 | 12.433 |
| gpu-uni-s8320-align64 | 8320 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 9921024 | 20.63 | 12.401 |
| host-bi-s132096 | 132096 | System | System | Enabled | 256 | 64 | 678400 | 44.90 | 22.095 |
| host-uni-s132096 | 132096 | System | System | Disabled | 256 | 64 | 723968 | 23.90 | 11.761 |
| rails4-gpu-bi-s1048576-cxi0 | 1048576 | GPU 0 | GPU 0 | Enabled | 256 | 64 | 107776 | 45.19 | 22.063 |
| rails4-gpu-bi-s1048576-cxi2 | 1048576 | GPU 2 | GPU 2 | Enabled | 256 | 64 | 107008 | 45.20 | 22.068 |
| rails4-gpu-bi-s132096-cxi3 | 132096 | GPU 3 | GPU 3 | Enabled | 256 | 64 | 848128 | 44.95 | 22.120 |

failed or no result rows:
  rails4-gpu-bi-s1048576-cxi1 rc=None Failed to connect to nid006052: Connection refused
  rails4-gpu-bi-s1048576-cxi3 rc=None Failed to connect to nid006052: Connection refused
  rails4-gpu-bi-s132096-cxi0 rc=None Failed to connect to nid006052: Connection refused
  rails4-gpu-bi-s132096-cxi1 rc=None Failed to connect to nid006052: Connection refused
  rails4-gpu-bi-s132096-cxi2 rc=None Failed to connect to nid006052: Connection refused
  rails4-host-uni-s1048576-cxi0 rc=None Failed to connect to nid006052: Connection refused
  rails4-host-uni-s1048576-cxi1 rc=None srun: error: Unable to create step for job 3833183: Job/step already completing or completed
  rails4-host-uni-s1048576-cxi2 rc=None Failed to connect to nid006052: Connection refused
  rails4-host-uni-s1048576-cxi3 rc=None Failed to connect to nid006052: Connection refused

22 result rows from 31 client files
