| test | size B | client TX mem | server RX mem | bidir | list | align | writes | GB/s (1e9 B/s) | Mpkt/s |
|---|---:|---|---|---|---:|---:|---:|---:|---:|
| host-bi-s1048576 | 1048576 | System | System | Enabled | 256 | 64 | 107776 | 45.12 | 22.030 |
| host-bi-s132096 | 132096 | System | System | Enabled | 256 | 64 | 846848 | 44.76 | 22.025 |
| host-bi-s65536 | 65536 | System | System | Enabled | 256 | 64 | 1698304 | 44.51 | 21.734 |
| host-uni-s1048576 | 1048576 | System | System | Disabled | 256 | 64 | 115456 | 24.17 | 11.800 |
| host-uni-s132096 | 132096 | System | System | Disabled | 256 | 64 | 904448 | 23.89 | 11.755 |
| host-uni-s16384 | 16384 | System | System | Disabled | 256 | 64 | 6635776 | 21.74 | 10.617 |
| host-uni-s262144 | 262144 | System | System | Disabled | 256 | 64 | 457984 | 24.00 | 11.718 |
| host-uni-s32768 | 32768 | System | System | Disabled | 256 | 64 | 3510784 | 23.01 | 11.234 |
| host-uni-s4096 | 4096 | System | System | Disabled | 256 | 64 | 20369408 | 16.69 | 8.147 |
| host-uni-s65536 | 65536 | System | System | Disabled | 256 | 64 | 1798400 | 23.57 | 11.508 |
| host-uni-s69120 | 69120 | System | System | Disabled | 256 | 64 | 1709312 | 23.63 | 11.622 |
| host-uni-s8192-align128 | 8192 | System | System | Disabled | 256 | 128 | 9499136 | 19.45 | 9.499 |
| host-uni-s8192-align64 | 8192 | System | System | Disabled | 256 | 64 | 9552128 | 19.56 | 9.552 |
| host-uni-s8192 | 8192 | System | System | Disabled | 256 | 64 | 11921664 | 19.53 | 9.537 |
| host-uni-s8256-align128 | 8256 | System | System | Disabled | 256 | 128 | 9436672 | 19.48 | 11.795 |
| host-uni-s8256-align64 | 8256 | System | System | Disabled | 256 | 64 | 9472000 | 19.55 | 11.840 |
| host-uni-s8320-align128 | 8320 | System | System | Disabled | 256 | 128 | 9363200 | 19.47 | 11.703 |
| host-uni-s8320-align64 | 8320 | System | System | Disabled | 256 | 64 | 9359360 | 19.47 | 11.699 |
| probe-svc | 65536 | System | System | Disabled | 256 | 64 | 719360 | 23.56 | 11.506 |
| rails4-host-uni-s1048576-cxi2 | 1048576 | System | System | Disabled | 256 | 64 | 138496 | 24.17 | 11.800 |

failed or no result rows:
  gpu-bi-s1048576 rc=1 Unable to open libcudart.so
  gpu-bi-s132096 rc=1 Unable to open libcudart.so
  gpu-bi-s65536 rc=1 Unable to open libcudart.so
  gpu-uni-s1048576 rc=1 Unable to open libcudart.so
  gpu-uni-s132096-l1 rc=1 Unable to open libcudart.so
  gpu-uni-s132096-l16 rc=1 Unable to open libcudart.so
  gpu-uni-s132096 rc=1 Unable to open libcudart.so
  gpu-uni-s16384 rc=1 Unable to open libcudart.so
  gpu-uni-s262144 rc=1 Unable to open libcudart.so
  gpu-uni-s32768 rc=1 Unable to open libcudart.so
  gpu-uni-s4096 rc=1 Unable to open libcudart.so
  gpu-uni-s65536 rc=1 Unable to open libcudart.so
  gpu-uni-s69120 rc=1 Unable to open libcudart.so
  gpu-uni-s8192-align128 rc=1 Unable to open libcudart.so
  gpu-uni-s8192-align64 rc=1 Unable to open libcudart.so
  gpu-uni-s8192 rc=1 Unable to open libcudart.so
  gpu-uni-s8256-align128 rc=1 Unable to open libcudart.so
  gpu-uni-s8256-align64 rc=1 Unable to open libcudart.so
  gpu-uni-s8320-align128 rc=1 Unable to open libcudart.so
  gpu-uni-s8320-align64 rc=1 Unable to open libcudart.so
  rails4-gpu-bi-s1048576-cxi0 rc=1 Failed to connect to nid007470: Connection refused
  rails4-gpu-bi-s1048576-cxi1 rc=1 Unable to open libcudart.so
  rails4-gpu-bi-s1048576-cxi2 rc=1 Failed to connect to nid007470: Connection refused
  rails4-gpu-bi-s1048576-cxi3 rc=1 Unable to open libcudart.so
  rails4-gpu-bi-s132096-cxi0 rc=1 Failed to connect to nid007470: Connection refused
  rails4-gpu-bi-s132096-cxi1 rc=1 Unable to open libcudart.so
  rails4-gpu-bi-s132096-cxi2 rc=1 Failed to connect to nid007470: Connection refused
  rails4-gpu-bi-s132096-cxi3 rc=1 Unable to open libcudart.so
  rails4-host-uni-s1048576-cxi0 rc=1 Failed to connect to nid007470: Connection refused
  rails4-host-uni-s1048576-cxi1 rc=1 Failed to connect to nid007470: Connection refused
  rails4-host-uni-s1048576-cxi3 rc=1 Failed to connect to nid007470: Connection refused

20 result rows from 51 client files
