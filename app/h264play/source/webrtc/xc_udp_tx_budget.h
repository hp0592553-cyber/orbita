/*
 * Bounded batching for the Xbox network-thread UDP transmit queues.
 *
 * The consumer runs on hw1 beside Wi-Fi and USB controller polling. Snapshot
 * the producer index and consume only a small slice per scheduler pass.
 */
#ifndef XCLOUD360_XCW_UDP_TX_BUDGET_H
#define XCLOUD360_XCW_UDP_TX_BUDGET_H

#include <stdint.h>

#define XCW_UDP_TX_SOCKET_BUDGET 4u

static inline uint32_t xcw_udp_tx_batch_end(uint32_t read_index,
                                            uint32_t write_snapshot,
                                            uint32_t budget) {
    uint32_t pending = write_snapshot - read_index;
    if (pending > budget) pending = budget;
    return read_index + pending;
}

#endif
