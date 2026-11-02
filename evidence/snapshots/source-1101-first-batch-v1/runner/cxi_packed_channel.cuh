#pragma once
#ifdef __CUDACC__
#define CXI_PACK_HD __host__ __device__
#else
#define CXI_PACK_HD
#endif
namespace deep_ep { namespace elastic {
// Sum the actual capacities of preceding strided channels, without padding.
CXI_PACK_HD constexpr int packed_channel_base(int max_tokens, int channels, int channel) {
    return channel * (max_tokens / channels) +
           (channel < max_tokens % channels ? channel : max_tokens % channels);
}
}}
#undef CXI_PACK_HD
