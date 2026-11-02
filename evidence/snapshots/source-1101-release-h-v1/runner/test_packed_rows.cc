#include "cxi_packed_channel.cuh"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <random>
#include <vector>

int main() {
    std::mt19937 random(20261031);
    unsigned long long cases=0, rows=0, batches=0;
    std::vector<int> sizes;
    for(int n=1;n<=513;n++)sizes.push_back(n);
    for(int n:{1023,1024,4095,4096,4097,16384})sizes.push_back(n);
    for(int maximum:sizes)for(int channels:{4,12,64,128,256}) {
        // Independent enumeration of input-token ownership establishes capacity.
        std::vector<std::vector<int>> owned(channels);
        for(int token=0;token<maximum;token++)owned[token%channels].push_back(token);
        int expected_base=0;
        for(int channel=0;channel<channels;channel++) {
            assert(deep_ep::elastic::packed_channel_base(maximum,channels,channel)==expected_base);
            expected_base+=owned[channel].size();
        }
        assert(expected_base==maximum);
        for(int interval:{1,3,8,16,64})for(int pattern=0;pattern<5;pattern++) {
            std::vector<int> source(maximum,-1);
            for(int channel=0;channel<channels;channel++) {
                const int base=deep_ep::elastic::packed_channel_base(maximum,channels,channel);
                std::vector<int> reference,received;
                int submitted=0;
                const auto publish=[&]() {
                    int pending=static_cast<int>(reference.size())-submitted;
                    if(!pending)return;
                    for(int i=0;i<pending;i++)received.push_back(source.at(base+submitted+i));
                    submitted+=pending;batches++;
                };
                for(int token:owned[channel]) {
                    bool remote=pattern==0 || (pattern==2 && token%2) ||
                                (pattern==3 && random()%4==0) || (pattern==4 && random()%4!=0);
                    if(!remote)continue;
                    int slot=base+reference.size();assert(source.at(slot)==-1);
                    source.at(slot)=token;reference.push_back(token);rows++;
                    if(static_cast<int>(reference.size())-submitted>=interval)publish();
                }
                publish();assert(received==reference);
                assert(submitted==static_cast<int>(reference.size()));cases++;
            }
        }
    }
    std::printf("PASS packed channel layout/source lifetime model: cases=%llu rows=%llu batches=%llu; GPU untested\n",cases,rows,batches);
}
