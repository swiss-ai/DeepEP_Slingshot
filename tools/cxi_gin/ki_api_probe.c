/* Compile-only check of the extension entry points used by pinned CLIC.
 * This does NOT query a live provider or prove compatibility with its ABI.
 */
#include <rdma/fabric.h>
#include <rdma/fi_domain.h>
#include <rdma/fi_endpoint.h>
#include <rdma/fi_cxi_ext.h>
#include <rdma/fi_cxi_gpu_ext.h>

void clic_ki_header_check(void) {
    const char *ki_ops = FI_CXI_KI_OPS;
    const char *counter_ops = FI_CXI_COUNTER_OPS;
    int endpoint_hints = FI_OPT_CXI_SET_KI_EP_HINTS;
    (void)ki_ops;
    (void)counter_ops;
    (void)endpoint_hints;
}
