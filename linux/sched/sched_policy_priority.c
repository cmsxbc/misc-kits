#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sched.h>
#include <threads.h>


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

static inline time_t get_time() {
    struct timespec t;
    if (-1 == clock_gettime(CLOCK_REALTIME, &t)) {
        exit_api_error("get time failed");
    }
    return t.tv_sec;
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

struct result_queue {
    time_t timestamp;
    nsec_t mean_diff;
    nsec_t min_diff;
    nsec_t max_diff;
    nsec_t top10n_diff;
    struct result_queue *next;
};

static struct result_queue result_end_msg;

struct thread_args {
    int policy;
    struct sched_param param;
    nsec_t sleep_time_ns;
    long interval;
    long total_times;
    struct result_queue* result_head;
    struct result_queue** result_tail;
};

void set_default_thead_args(struct thread_args *args, struct result_queue *result_head) {
    args->policy = SCHED_OTHER;
    args->param.sched_priority = 0;
    args->sleep_time_ns = 20000000; // 20 ms;
    args->interval = 1000000000; // 1s;
    args->total_times = 50;
    args->result_head = result_head;
    args->result_tail = &result_head->next;
}

int thread_func(void * args) {
    struct thread_args *targs = (struct thread_args*) args;
    set_scheduler(targs->policy, &targs->param);
    nsec_t sleep_time_ns = targs->sleep_time_ns;
    useconds_t sleep_time = sleep_time_ns / 1000;
    long interval = targs->interval;
    long total_times = targs->total_times;
    long max_times = interval / sleep_time_ns;
    long top10n = max_times - max_times * 9 / 10;
    heap_t heap = create_heap(top10n);
    // printf("times, mean, [min, %ldth, max]\n", top10n);
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
        // printf("%d, %ld, %lld, [%lld, %lld, %lld]\n", targs->policy, max_times, total_diff / max_times, min_diff, heap[0], max_diff);
        struct result_queue* node = (struct result_queue*) malloc(sizeof(struct result_queue));
        if (node == NULL) {
            exit_api_error("alloc result failed");
        }
        node->timestamp = get_time();
        node->mean_diff = total_diff / max_times;
        node->min_diff = min_diff;
        node->top10n_diff = heap[0];
        node->max_diff = max_diff;
        node->next = NULL;
        *targs->result_tail = node;
        targs->result_tail = &node->next;
    }
    *targs->result_tail = &result_end_msg;
    delete_heap(heap);
    return thrd_success;
}

int main(int argc, char const *argv[]) {
    if (argc <= 1) {
        printf("usage: %s policy1 [policy2 [policy3 ...]]", argv[0]);
        exit(2);
    }
    int thread_count = argc - 1;
    struct thread_args *args = calloc(thread_count, sizeof(struct thread_args));
    for (int i = 0; i < thread_count; i++) {
        set_default_thead_args(&args[i], malloc(sizeof(struct result_queue)));
        if (strcmp(argv[i+1], "IDLE") == 0) {
            args[i].policy = SCHED_IDLE;
        } else if (strcmp(argv[i+1], "FIFO") == 0) {
            args[i].policy = SCHED_FIFO;
            args[i].param.sched_priority = 1;
        } else if (strcmp(argv[i+1], "RR") == 0) {
            args[i].policy = SCHED_RR;
            args[i].param.sched_priority = 1;
        } else if (strcmp(argv[i+1], "NORMAL") == 0) {
            // although it's default;
            args[i].policy = SCHED_OTHER;
        } else {
            printf("unknown scheduler policy: %s", argv[i+1]);
            exit(EXIT_LOGICAL);
        }
    }
    thrd_t *threads = calloc(thread_count, sizeof(thrd_t));
    for (int i = 0; i < thread_count; i++) {
        if (thrd_create(&threads[i], thread_func, &args[i]) != thrd_success) {
            exit_api_error("create thread failed");
        }
    }
    int nr_running = thread_count;
    struct timespec sleep_main = {0, 1000000};
    do {
        thrd_sleep(&sleep_main, NULL);
        int nr_result = 0;
        for (int i = 0; i < thread_count; i ++) {
            if (args[i].result_head->next != NULL) {
                nr_result += 1;
            }
        }
        if (nr_result < nr_running) {
            continue;
        }
        printf("threads, policy, mean, [min, top10n th, max]\n");
        for (int i = 0; i < thread_count; i ++) {
            struct result_queue *result = args[i].result_head->next;
            if (result == NULL) {
                continue;
            }
            if (result == &result_end_msg) {
                printf("thread %d finished!\n", i);
                nr_running --;
            } else {
                printf("%d, %d, %lld, [%lld, %lld, %lld]\n", i, args[i].policy, result->mean_diff, result->min_diff, result->top10n_diff,
                       result->max_diff);
            }
            free(args[i].result_head);
            args[i].result_head = result;
        }
        printf("======================================\n");
    } while(nr_running > 0);
    for (int i = 0; i < 2; i++) {
        thrd_join(threads[i], NULL);
    }
    free(threads);
    free(args);
    return 0;
}
