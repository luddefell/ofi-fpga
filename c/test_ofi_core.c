/* Replays vectors.csv (generated from the Python reference OFICore by
 * gen_vectors.py) through the C port and asserts bit-exact agreement on
 * every row. This is spec section 5 Stage 1: Python <-> C, the first leg
 * of the three-stage verification flow, before RTL is involved at all.
 */
#include "ofi_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define K_DECAY 6
#define THETA_Q16 6554

static int run_csv(const char *path) {
    FILE *f = fopen(path, "r");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", path);
        return 1;
    }

    char line[512];
    if (!fgets(line, sizeof(line), f)) { /* header */
        fclose(f);
        return 1;
    }

    ofi_core_t core;
    ofi_core_init(&core, K_DECAY, THETA_Q16);

    long row = 0;
    int mismatches = 0;

    while (fgets(line, sizeof(line), f)) {
        ofi_top_t t;
        long long exp_e, exp_acc, exp_flags;

        int n = sscanf(line, "%d,%d,%d,%d,%lld,%lld,%lld",
                        &t.bid_px, &t.bid_qty, &t.ask_px, &t.ask_qty,
                        &exp_e, &exp_acc, &exp_flags);
        if (n != 7) {
            fprintf(stderr, "malformed row %ld: %s", row, line);
            fclose(f);
            return 1;
        }

        ofi_result_t r = ofi_core_event(&core, t);

        if (r.e_n != exp_e || r.acc != exp_acc || r.flags != exp_flags) {
            fprintf(stderr,
                    "MISMATCH row %ld: got (e=%d, acc=%lld, flags=%u) "
                    "expected (e=%lld, acc=%lld, flags=%lld)\n",
                    row, r.e_n, (long long)r.acc, r.flags, exp_e, exp_acc, exp_flags);
            mismatches++;
        }
        row++;
    }

    fclose(f);
    printf("%ld rows replayed, %d mismatches\n", row, mismatches);
    return mismatches != 0;
}

static void test_first_event_is_seed(void) {
    ofi_core_t core;
    ofi_core_init(&core, K_DECAY, THETA_Q16);
    ofi_top_t t = {100, 10, 101, 10};
    ofi_result_t r = ofi_core_event(&core, t);
    if (r.e_n != 0 || r.acc != 0 || r.flags != 0) {
        fprintf(stderr, "test_first_event_is_seed FAILED\n");
        exit(1);
    }
    printf("test_first_event_is_seed passed\n");
}

static void test_bid_up_counts_full_new_queue(void) {
    ofi_core_t core;
    ofi_core_init(&core, K_DECAY, THETA_Q16);
    ofi_core_event(&core, (ofi_top_t){100, 10, 101, 10});
    ofi_result_t r = ofi_core_event(&core, (ofi_top_t){101, 30, 101, 10});
    if (r.e_n != 30) {
        fprintf(stderr, "test_bid_up_counts_full_new_queue FAILED: e_n=%d\n", r.e_n);
        exit(1);
    }
    printf("test_bid_up_counts_full_new_queue passed\n");
}

static void test_sat32_saturates(void) {
    if (ofi_sat32((int64_t)1 << 40) != INT32_MAX) {
        fprintf(stderr, "test_sat32_saturates FAILED (positive)\n");
        exit(1);
    }
    if (ofi_sat32(-((int64_t)1 << 40)) != INT32_MIN) {
        fprintf(stderr, "test_sat32_saturates FAILED (negative)\n");
        exit(1);
    }
    printf("test_sat32_saturates passed\n");
}

int main(int argc, char **argv) {
    test_first_event_is_seed();
    test_bid_up_counts_full_new_queue();
    test_sat32_saturates();

    const char *csv_path = argc > 1 ? argv[1] : "vectors.csv";
    return run_csv(csv_path);
}
