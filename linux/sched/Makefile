all: clean-all build
build: sched_policy_priority
sched_policy_priority: sched_policy_priority.c
	gcc -Wall -O2 -std=c11 -lpthread -o $@ $<

clean-all:
	rm -f sched_policy_priority
