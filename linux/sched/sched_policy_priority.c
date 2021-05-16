#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sched.h>


#define EXIT_API_ERROR 1
#define EXIT_LOGICAL 2

#define exit_error(errno, err) do \
{ \
    perror(err); \
    exit(errno); \
} while (0);

#define exit_api_error(err) exit_error(EXIT_API_ERROR, err)

typedef long long nsec_t;

typedef nsec_t heap_ele_t;
typedef nsec_t *heap_t;

void set_scheduler(int policy, const struct sched_param *param) {
    pid_t tid = gettid();
    if (-1 == sched_setscheduler(tid, policy, param)) {
        exit_api_error("set scheduler policy failed");
    }
}

static inline nsec_t get_time_ns(const char *err) {
    struct timespec t;
    if (-1 == clock_gettime(CLOCK_MONOTONIC, &t)) {
        exit_api_error(err);
    }
    return t.tv_nsec + t.tv_sec * 1000000000;
}

static inline heap_t create_heap(long size) {
    heap_t heap = calloc(size, sizeof(heap_ele_t));
    if (heap == NULL) {
        exit_api_error("alloc heap failed");
    }
    return heap;
}

static inline void clear_heap(heap_t heap, long size) {
    bzero(heap, size * sizeof(heap_ele_t));
}

static inline void delete_heap(heap_t heap) {
    free(heap);
}

#define swap_heap(a, b) \
do {                    \
    heap_ele_t tmp = heap[a]; \
    heap[a] = heap[b];  \
    heap[b] = tmp;      \
} while (0);

static inline long maintain_topN(heap_t heap, heap_ele_t ele, long size, long max_size) {
    if (ele < heap[0]) {
        return size;
    }
    if (size < max_size) {
        heap[size] = ele;

        long cur_idx = size;
        while (cur_idx > 0) {
            long parent = (cur_idx - 1) / 2;
            if (heap[parent] > heap[cur_idx]) {
                swap_heap(parent, cur_idx);
                cur_idx = parent;
            } else {
                cur_idx = 0;
            }
        }
        return size + 1;
    } else {
        heap[0] = ele;
        long cur_idx = 0;
        while (cur_idx < size) {
            long smallest = cur_idx;
            long l = cur_idx * 2;
            long r = cur_idx * 2 + 1;
            if (l < size && heap[l] < heap[cur_idx]) {
                smallest = l;
            }
            if (r < size && heap[r] < heap[cur_idx]) {
                smallest = r;
            }
            if (smallest != cur_idx) {
                swap_heap(smallest, cur_idx);
                cur_idx = smallest;
            } else {
                cur_idx = size;
            }
        }
        return size;
    }
}

int main(int argc, char const *argv[]) {
    if (argc <= 1) {
        printf("usage: %s [sched_policy [sched_priority]]", argv[0]);
        exit(EXIT_LOGICAL);
    }
    if (argc >= 2) {
        struct sched_param param = {};
        if (argc >= 3) {
            param.sched_priority = atoi(argv[2]);
        }
        if (strcmp(argv[1], "IDLE") == 0) {
            set_scheduler(SCHED_IDLE, &param);
        } else if (strcmp(argv[1], "FIFO") == 0) {
            if (argc < 3) {
                param.sched_priority = 1;
            }
            set_scheduler(SCHED_FIFO, &param);
        } else if (strcmp(argv[1], "RR") == 0) {
            if (argc < 3) {
                param.sched_priority = 1;
            }
            set_scheduler(SCHED_RR, &param);
        } else if (strcmp(argv[1], "NORMAL") == 0) {
            // although it's default;
            set_scheduler(SCHED_OTHER, &param);
        } else {
            printf("unknown scheduler policy: %s", argv[1]);
            exit(EXIT_LOGICAL);
        }
    }
    useconds_t sleep_time = 20000;
    nsec_t sleep_time_ns = sleep_time * 1000;
    long interval = 1000000000;
    long total_times = 100;
    long max_times = interval / sleep_time_ns;
    long top10n = max_times - max_times * 9 / 10;
    heap_t heap = create_heap(top10n);
    printf("times, mean, [min, %ldth, max]\n", top10n);
    while (total_times -- > 0) {
        nsec_t s = 0, e = 0, d = 0;
        nsec_t total_diff = 0, max_diff = 0, min_diff = (1ULL << 63) - 1;
        clear_heap(heap, top10n);
        long cur_size = 0;
        for (long i = 0; i < max_times; i++) {
            s = get_time_ns("get start time");
            usleep(sleep_time);
            e = get_time_ns("get end time");
            d = e - s - sleep_time_ns;
            total_diff += d;
            min_diff = min_diff < d ? min_diff : d;
            max_diff = max_diff > d ? max_diff : d;
            cur_size = maintain_topN(heap, d, cur_size, top10n);
        }
        printf("%ld, %lld, [%lld, %lld, %lld]\n", max_times, total_diff / max_times, min_diff, heap[0], max_diff);
    }
    delete_heap(heap);
    return 0;
}
