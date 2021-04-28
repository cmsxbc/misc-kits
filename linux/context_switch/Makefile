build: tcsw
	$(info, "build done")

tcsw: analyse_threads_context_switch.cc
	g++ $< --std=c++17 -o tcsw -Wall

all: build
    $(info, "all done")