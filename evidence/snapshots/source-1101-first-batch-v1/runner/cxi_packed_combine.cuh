#pragma once
#ifdef __CUDACC__
#define CXI_PACKC_HD __host__ __device__
#else
#define CXI_PACKC_HD
#endif
namespace deep_ep { namespace elastic {
// Channel-major slot of token `t` inside one scale-out receive layer. Bijective on
// [0, max_tokens): channel c = t % channels owns slots [base(c), base(c) + count(c)).
CXI_PACKC_HD constexpr int packed_combine_slot(int max_tokens, int channels, int t) {
    const int c = t % channels;
    return c * (max_tokens / channels) + (c < max_tokens % channels ? c : max_tokens % channels) + t / channels;
}
}}
#undef CXI_PACKC_HD
