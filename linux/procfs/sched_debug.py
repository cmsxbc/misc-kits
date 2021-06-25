import os
import sys
import time


SD_PATH = '/proc/sched_debug'

assert os.uname().sysname == 'Linux', "linux only !!!"
assert os.path.exists(SD_PATH), f"{SD_PATH} does not exist !!! Kernel should be built with CONFIG_SCHED_DEBUG=y"


def get_loadavg_param():
    with open(SD_PATH) as f:
        in_cpu_info = False
        nr_running = 0
        nr_uninterruptible = 0
        for line in f.readlines():
            if in_cpu_info and line.startswith('  .nr_running'):
                nr_running += int(line.split(':')[1].strip())
            elif line.startswith('cpu#'):
                in_cpu_info = True
            elif line.startswith('  .nr_uninterruptible'):
                nr_uninterruptible += int(line.split(':')[1].strip())
            elif in_cpu_info and line[0] != ' ':
                in_cpu_info = False
        return nr_running, nr_uninterruptible


def get_running_task(state='R', with_key_line=True):
    with open(SD_PATH) as f:
        cur_cpu = None
        in_task_list = 0
        running_tasks = {}
        key_line = ''
        for line in f.readlines():
            if line.startswith('cpu#'):
                cur_cpu = line[4:line.find(',')]
                running_tasks[cur_cpu] = []
            elif line.startswith('runnable tasks:'):
                in_task_list = 1
            elif in_task_list == 1:
                if len(key_line) == 0:
                    key_line = line.rstrip()
                if line[0] == '-':
                    in_task_list = 2
            elif in_task_list == 2:
                if len(line) < 2 or line[1] == ' ':
                    in_task_list = 0
                    continue
                if line[1] == state:
                    running_tasks[cur_cpu].append(line.rstrip())
        if with_key_line:
            return running_tasks, key_line
        return running_tasks


def monitor_loadavg_param(interval=1.0):
    while True:
        print(time.time(), get_loadavg_param(), flush=True)
        time.sleep(interval)


def print_running_task(state='R'):
    running_tasks, key_line = get_running_task(state, with_key_line=True)
    print(key_line)
    for cpu_id, tasks in running_tasks.items():
        if len(tasks) == 0:
            continue
        print('='*120)
        print(f'cpu#{cpu_id}')
        print('-'*120)
        for task in tasks:
            print(task)
        print(flush=True)


def print_usage():
    print('usage:', sys.argv[0], 'loadavg_param | task_list [state]', file=sys.stderr)
    sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print_usage()
    if sys.argv[1] == 'loadavg_param':
        if len(sys.argv) == 3:
            interval = float(sys.argv[2])
            monitor_loadavg_param(interval)
        else:
            monitor_loadavg_param()
    elif sys.argv[1] == 'task_list':
        if len(sys.argv) >= 3:
            assert len(sys.argv[2]) == 1, "state should be only one character"
            print_running_task(sys.argv[2])
        else:
            print_running_task()
    else:
        print_usage()
