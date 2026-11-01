#include "../../source/webrtc/xc_udp_tx_budget.h"

#include <stdio.h>

static unsigned checks;
static unsigned failures;

#define CHECK(expr) do { \
    checks++; \
    if (!(expr)) { \
        failures++; \
        fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #expr); \
    } \
} while (0)

int main(void) {
    CHECK(xcw_udp_tx_batch_end(0u, 0u, 4u) == 0u);
    CHECK(xcw_udp_tx_batch_end(10u, 13u, 4u) == 13u);
    CHECK(xcw_udp_tx_batch_end(10u, 30u, 4u) == 14u);
    CHECK(xcw_udp_tx_batch_end(10u, 30u, 0u) == 10u);
    CHECK(xcw_udp_tx_batch_end(10u, 30u, 16u) == 26u);

    /* 32-bit producer/consumer counters may wrap while a queue is live. */
    CHECK(xcw_udp_tx_batch_end(0xfffffffeu, 4u, 4u) == 2u);
    CHECK(xcw_udp_tx_batch_end(0xfffffffeu, 4u, 16u) == 4u);

    if (failures) {
        fprintf(stderr, "%u/%u checks failed\n", failures, checks);
        return 1;
    }
    printf("UDP TX budget: %u checks passed\n", checks);
    return 0;
}
