#define _GNU_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sched.h>
#include <threads.h>
#include <getopt.h>
#include <syscall.h>
#include <pthread.h>


#define EXIT_API_ERROR 1
#define EXIT_PARAM_ERROR 2
#define EXIT_LOGICAL_ERROR 3

#define exit_perror(errno, err) do \
{ \
    perror(err); \
    exit(errno); \
} while (0);

#define exit_fprintf(errno, fd, ...) do \
{                                  \
    fprintf(stderr, __VA_ARGS__);  \
    exit(errno);                   \
} while (0);

#define exit_api_error(err) exit_perror(EXIT_API_ERROR, err)
#define exit_param_error(...) exit_fprintf(EXIT_PARAM_ERROR, stderr, __VA_ARGS__)
#define exit_logic_error(...) exit_fprintf(EXIT_LOGICAL_ERROR, stderr, __VA_ARGS__)

typedef long long nsec_t;

typedef nsec_t heap_ele_t;
typedef nsec_t *heap_t;


static inline const char * get_policy_name(int policy) {
    switch (policy) {
        case SCHED_OTHER:
            return "SCHED_NORMAL";
        case SCHED_BATCH:
            return "SCHED_BATCH";
        case SCHED_RR:
            return "SCHED_RR";
        case SCHED_FIFO:
            return "SCHED_FIFO";
        case SCHED_DEADLINE:
            return "SCHED_DEADLINE";
        case SCHED_IDLE:
            return "SCHED_IDLE";
        default:
            return "SCHED_UNKNOWN";
    }
}


struct sched_attr {
    u_int32_t size;
    u_int32_t policy;
    u_int64_t flags;
    int32_t nice;
    u_int32_t priority;
    u_int64_t runtime;
    u_int64_t deadline;
    u_int64_t period;
};

void set_scheduler(int policy, const struct sched_param *param) {
    pid_t tid = gettid();
    if (-1 == sched_setscheduler(tid, policy, param)) {
        exit_api_error("set scheduler policy failed");
    }
}

void set_default_sched_attr(int policy, struct sched_attr *attr) {
    attr->size = sizeof(struct sched_attr);
    attr->policy = policy;
    attr->flags = 0;
    switch (policy) {
        case SCHED_OTHER:
        case SCHED_BATCH:
            attr->nice = 0;
            break;
        case SCHED_FIFO:
        case SCHED_RR:
            attr->priority = 1;
            break;
        case SCHED_IDLE:
            attr->nice = 0;
            attr->priority = 0;
            break;
        case SCHED_DEADLINE:
            attr->runtime = 1000000000;
            attr->deadline = 1000000000;
            attr->period = 1000000000;
            break;
        default:
            exit_logic_error("unknown supported policy: %s(%d)", get_policy_name(policy), policy);
    }
}

void set_scheduler_attr(const struct sched_attr *attr) {
    pid_t tid = gettid();
    long ret = syscall(__NR_sched_setattr, tid, attr, 0);
    // printf("syscall return: %d, %ld\n", attr->policy, ret);
    if (ret == -1) {
        exit_api_error("set scheduler attr failed");
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
    struct sched_attr attr;
    nsec_t sleep_time_ns;
    long interval;
    long total_times;
    struct result_queue* result_head;
    struct result_queue** result_tail;
    pid_t tid;
};

void set_default_thead_args(struct thread_args *args, struct result_queue *result_head) {
    args->policy = SCHED_OTHER;
    set_default_sched_attr(args->policy, &args->attr);
    args->sleep_time_ns = 20000000; // 20 ms;
    args->interval = 1000000000; // 1s;
    args->total_times = 50;
    args->result_head = result_head;
    args->result_tail = &result_head->next;
}

int thread_func(void * args) {
    struct thread_args *targs = (struct thread_args*) args;
    set_scheduler_attr(&targs->attr);
    nsec_t sleep_time_ns = targs->sleep_time_ns;
    useconds_t sleep_time = sleep_time_ns / 1000;
    long interval = targs->interval;
    long total_times = targs->total_times;
    long max_times = interval / sleep_time_ns;
    long top10n = max_times - max_times * 9 / 10;
    heap_t heap = create_heap(top10n);
    // printf("times, mean, [min, %ldth, max]\n", top10n);
    targs->tid = gettid();
    pthread_setname_np(pthread_self(), get_policy_name(targs->policy));
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


void do_mt(int thread_count, struct thread_args *args) {
    thrd_t *threads = calloc(thread_count, sizeof(thrd_t));
    if (threads == NULL) {
        exit_api_error("alloc threads failed");
    }
    for (int i = 0; i < thread_count; i++) {
        printf("create thread %d with policy %s\n", i, get_policy_name(args[i].policy));
        if (thrd_create(&threads[i], thread_func, &args[i]) != thrd_success) {
            exit_api_error("create thread failed");
        }
    }
    int nr_running = thread_count;
    pid_t pid = getpid();
    do {
        sched_yield();
        int nr_result = 0;
        for (int i = 0; i < thread_count; i ++) {
            if (args[i].result_head->next != NULL) {
                nr_result += 1;
            }
        }
        if (nr_result < nr_running) {
            continue;
        }
        printf("pid: %d\n", pid);
        // printf("  threads,          policy,  timestamp,      mean, [      min,       P90,      max]\n");
        printf("%3s(%7s), %14s, %10s, %9s, [%-9s, %9s, %9s]\n", "no", "tid", "policy", "timestamp", "mean", "min", "p90", "max");
        for (int i = 0; i < thread_count; i ++) {
            struct result_queue *result = args[i].result_head->next;
            if (result == NULL) {
                continue;
            }
            if (result == &result_end_msg) {
                printf("thread %d finished!\n", i);
                nr_running --;
            } else {
                printf("%3d(%7d), %14s, %10ld, %9lld, [%-9lld, %9lld, %9lld]\n", i, args[i].tid,
                       get_policy_name(args[i].policy), result->timestamp,
                       result->mean_diff, result->min_diff, result->top10n_diff, result->max_diff);
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
}

int main(int argc, char const *argv[]) {
    if (argc <= 1) {
        exit_param_error("usage: %s policy1 [policy2 [policy3 ...]]", argv[0]);
    }
    struct sched_param param = {0};
    set_scheduler(SCHED_OTHER, &param);
    int thread_count = argc - 1;
    struct thread_args *args = calloc(thread_count, sizeof(struct thread_args));
    for (int i = 0; i < thread_count; i++) {
        set_default_thead_args(&args[i], malloc(sizeof(struct result_queue)));
        if (strcmp(argv[i+1], "IDLE") == 0) {
            args[i].policy = SCHED_IDLE;
        } else if (strcmp(argv[i+1], "FIFO") == 0) {
            args[i].policy = SCHED_FIFO;
        } else if (strcmp(argv[i+1], "RR") == 0) {
            args[i].policy = SCHED_RR;
        } else if (strcmp(argv[i+1], "NORMAL") == 0) {
            // although it's default;
            args[i].policy = SCHED_OTHER;
        } else if (strcmp(argv[i+1], "DEADLINE") == 0) {
            args[i].policy = SCHED_DEADLINE;
        } else {
            exit_param_error("unknown scheduler policy: %s", argv[i+1]);
        }
        set_default_sched_attr(args[i].policy, &args[i].attr);
    }
    do_mt(thread_count, args);
    free(args);
    return 0;
}
