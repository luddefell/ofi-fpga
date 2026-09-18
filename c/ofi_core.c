#include "ofi_core.h"

#include <limits.h>

int32_t ofi_sat32(int64_t x) {
    if (x > INT32_MAX) return INT32_MAX;
    if (x < INT32_MIN) return INT32_MIN;
    return (int32_t)x;
}

void ofi_core_init(ofi_core_t *core, unsigned k_decay, uint32_t theta_q16) {
    core->k = k_decay;
    core->theta_q16 = theta_q16;
    core->has_prev = false;
    core->acc = 0;
    core->depth_acc = 0;
}

/* Spec section 4.2 rule 3: shifts are arithmetic and round toward negative
 * infinity. On every mainstream compiler (gcc, clang, MSVC) `>>` on a
 * signed integer type is already arithmetic, matching Python's `>>` on
 * negative ints -- this is documented per spec's requirement rather than
 * worked around, since no target compiler for this project behaves
 * otherwise. */
static int64_t arith_shr(int64_t x, unsigned k) {
    return x >> k;
}

ofi_result_t ofi_core_event(ofi_core_t *core, ofi_top_t t) {
    ofi_result_t r = {0, 0, 0};

    if (!core->has_prev) {
        core->prev = t;
        core->has_prev = true;
        core->depth_acc = ((int64_t)t.bid_qty + (int64_t)t.ask_qty) << core->k;
        return r; /* (0, 0, 0): seed only, not a signal */
    }

    ofi_top_t p = core->prev;

    /* --- OFI event term: 4 compares, 4 conditional adds --- */
    int64_t e = 0;
    if (t.bid_px >= p.bid_px) e += t.bid_qty;
    if (t.bid_px <= p.bid_px) e -= p.bid_qty;
    if (t.ask_px <= p.ask_px) e -= t.ask_qty;
    if (t.ask_px >= p.ask_px) e += p.ask_qty;
    int32_t e_sat = ofi_sat32(e);

    /* --- EWMA accumulate: one shift, two adds --- */
    core->acc = core->acc - arith_shr(core->acc, core->k) + e_sat;

    /* --- depth EWMA, same structure --- */
    int64_t d = (int64_t)t.bid_qty + (int64_t)t.ask_qty;
    core->depth_acc = core->depth_acc - arith_shr(core->depth_acc, core->k) + d;

    /* --- threshold WITHOUT division (spec section 3.2) --- */
    int64_t lhs = core->acc << 16;
    int64_t rhs = arith_shr((int64_t)core->theta_q16 * core->depth_acc, core->k);

    uint8_t flags = 0;
    if (lhs > rhs) flags |= 0x1u;   /* buy pressure */
    if (lhs < -rhs) flags |= 0x2u;  /* sell pressure */

    core->prev = t;

    r.e_n = e_sat;
    r.acc = core->acc;
    r.flags = flags;
    return r;
}
