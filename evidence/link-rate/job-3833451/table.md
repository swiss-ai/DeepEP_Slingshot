| test | size B | client TX mem | server RX mem | bidir | list | align | writes | GB/s (1e9 B/s) | Mpkt/s |
|---|---:|---|---|---|---:|---:|---:|---:|---:|
| gpu-uni-s107328-align128 | 107328 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 890368 | 23.88 | 11.794 |
| gpu-uni-s107328-align64 | 107328 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 890112 | 23.88 | 11.793 |
| gpu-uni-s115584-align128 | 115584 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 829952 | 23.98 | 11.824 |
| gpu-uni-s115584-align64 | 115584 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 828928 | 23.95 | 11.809 |
| gpu-uni-s123840-align128 | 123840 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 774144 | 23.96 | 11.804 |
| gpu-uni-s123840-align64 | 123840 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 774144 | 23.96 | 11.802 |
| gpu-uni-s132096-align128 | 132096 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 727296 | 24.01 | 11.815 |
| gpu-uni-s132096-align64 | 132096 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 725760 | 23.96 | 11.791 |
| gpu-uni-s132096-l8 | 132096 | GPU 0 | GPU 0 | Disabled | 8 | 64 | 628640 | 20.76 | 10.215 |
| gpu-uni-s60480-align128 | 60480 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 1566976 | 23.69 | 11.750 |
| gpu-uni-s60480-align64 | 60480 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 1566464 | 23.68 | 11.747 |
| gpu-uni-s64800-align128 | 64800 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 1464064 | 23.71 | 11.711 |
| gpu-uni-s64800-align32 | 64800 | GPU 0 | GPU 0 | Disabled | 256 | 32 | 1467392 | 23.77 | 11.738 |
| gpu-uni-s64800-align64 | 64800 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 1464576 | 23.73 | 11.716 |
| gpu-uni-s69120-align128 | 69120 | GPU 0 | GPU 0 | Disabled | 256 | 128 | 1375744 | 23.77 | 11.692 |
| gpu-uni-s69120-align64 | 69120 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 1374720 | 23.75 | 11.684 |
| gpu-uni-s69120-l8 | 69120 | GPU 0 | GPU 0 | Disabled | 8 | 64 | 1061536 | 18.34 | 9.023 |
| host-uni-s123840-align64 | 123840 | System | System | Disabled | 256 | 64 | 768768 | 23.79 | 11.720 |
| host-uni-s60480-align64 | 60480 | System | System | Disabled | 256 | 64 | 1569024 | 23.72 | 11.767 |
| rails4-gpu-bi-s1048576-cxi0 | 1048576 | GPU 0 | GPU 0 | Enabled | 256 | 64 | 61440 | 30.99 | 15.131 |
| rails4-gpu-bi-s1048576-cxi1 | 1048576 | GPU 1 | GPU 1 | Enabled | 256 | 64 | 61696 | 31.02 | 15.145 |
| rails4-gpu-bi-s1048576-cxi2 | 1048576 | GPU 2 | GPU 2 | Enabled | 256 | 64 | 58112 | 31.28 | 15.273 |
| rails4-gpu-bi-s1048576-cxi3 | 1048576 | GPU 3 | GPU 3 | Enabled | 256 | 64 | 57856 | 31.22 | 15.242 |
| rails4-gpu-bi-s132096-cxi0 | 132096 | GPU 0 | GPU 0 | Enabled | 256 | 64 | 854528 | 45.15 | 22.215 |
| rails4-gpu-bi-s132096-cxi1 | 132096 | GPU 1 | GPU 1 | Enabled | 256 | 64 | 853760 | 45.10 | 22.194 |
| rails4-gpu-bi-s132096-cxi2 | 132096 | GPU 2 | GPU 2 | Enabled | 256 | 64 | 853248 | 45.10 | 22.191 |
| rails4-gpu-bi-s132096-cxi3 | 132096 | GPU 3 | GPU 3 | Enabled | 256 | 64 | 853248 | 45.09 | 22.190 |
| rails4-gpu-uni-s132096-cxi0 | 132096 | GPU 0 | GPU 0 | Disabled | 256 | 64 | 907008 | 23.96 | 11.788 |
| rails4-gpu-uni-s132096-cxi1 | 132096 | GPU 1 | GPU 1 | Disabled | 256 | 64 | 907008 | 23.96 | 11.789 |
| rails4-gpu-uni-s132096-cxi2 | 132096 | GPU 2 | GPU 2 | Disabled | 256 | 64 | 908800 | 24.00 | 11.811 |
| rails4-gpu-uni-s132096-cxi3 | 132096 | GPU 3 | GPU 3 | Disabled | 256 | 64 | 906496 | 23.95 | 11.783 |
| rails4-host-bi-s132096-cxi0 | 132096 | System | System | Enabled | 256 | 64 | 832512 | 44.89 | 22.090 |
| rails4-host-bi-s132096-cxi1 | 132096 | System | System | Enabled | 256 | 64 | 850944 | 44.88 | 22.085 |
| rails4-host-bi-s132096-cxi2 | 132096 | System | System | Enabled | 256 | 64 | 853760 | 44.86 | 22.076 |
| rails4-host-bi-s132096-cxi3 | 132096 | System | System | Enabled | 256 | 64 | 869120 | 44.84 | 22.065 |
| rails4-host-uni-s1048576-cxi0 | 1048576 | System | System | Disabled | 256 | 64 | 110080 | 23.07 | 11.265 |
| rails4-host-uni-s1048576-cxi1 | 1048576 | System | System | Disabled | 256 | 64 | 110080 | 23.07 | 11.267 |
| rails4-host-uni-s1048576-cxi2 | 1048576 | System | System | Disabled | 256 | 64 | 109568 | 22.97 | 11.217 |
| rails4-host-uni-s1048576-cxi3 | 1048576 | System | System | Disabled | 256 | 64 | 109568 | 22.96 | 11.213 |

39 result rows from 39 client files
