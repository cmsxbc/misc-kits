#include <iostream>
#include <fstream>
#include <filesystem>
#include <vector>
#include <chrono>
#include <map>
#include <algorithm>
#include <thread>


std::vector<std::string> read_proc_file()
{
    if (!std::filesystem::exists("/proc/sched_debug")) {
        throw std::runtime_error("kernel should be built with CONFIG_SCHED_DEBUG=y!!");
    }
    std::ifstream f("/proc/sched_debug");
    std::vector<std::string> lines;
    while (!f.eof()) {
        std::string line;
        std::getline(f, line);
        lines.push_back(line);
    }
    return lines;
}

class Process {
public:
    explicit Process(int pid, std::string cmdline, long nr_switch): m_pid(pid), m_cmdline(std::move(cmdline)), m_nr_switch(nr_switch), m_diffs(5) {};
    ~Process() = default;
    void add(long nr_switch) {
        auto diff = nr_switch - m_nr_switch;
        m_diffs.push_back(diff);
        m_nr_switch = nr_switch;
    }
    long long total_diff() {
        long long s = 0;
        for (auto &diff : m_diffs) {
            s += diff;
        }
        return s;
    }
    [[nodiscard]] int pid() const { return m_pid; }
    [[nodiscard]] long nr_switch() const { return m_nr_switch; }
    [[nodiscard]] std::string cmdline() const { return m_cmdline; }

private:
    int m_pid;
    std::string m_cmdline;
    long m_nr_switch;
    std::vector<long> m_diffs;
};

class Result {
public:
    void add_process(Process * process) {
        processes.emplace(process->pid(), process);
    }
    bool exists(int pid) {
        return processes.find(pid) != processes.end();
    }
    Process* operator[](int pid) {
        return processes[pid];
    }
    void print_all() {
        for (auto && [pid, process]: processes) {
            std::cout << process->pid() << "," << process->nr_switch() << std::endl;
        }
    }
    void print_topN(int n) {
        std::vector<std::pair<int, Process *>> results(n);
        std::partial_sort_copy(processes.begin(), processes.end(), results.begin(), results.end(), [](const auto & i, const auto &j) {
            return i.second->total_diff() >= j.second->total_diff();
        });
        int count = 0;
        std::cout << std::setw(3) << count++ << ": "
            << std::setw(5) << "TID" << ", "
            << std::setw(15) << "CMDLINE" << ", "
            << std::setw(9) << "NR_SWITCH" << ", "
            << std::setw(9) << "INCREASE" << std::endl;
        for (auto & [pid, process]: results) {
            std::cout << std::setw(3) << count++ << ": "
                << std::setw(5) << process->pid() << ", "
                << std::setw(15) << process->cmdline() << ", "
                << std::setw(9) << process->nr_switch() << ", "
                << std::setw(9) << process->total_diff() << std::endl;
        }
    }
private:
    std::map<int, Process *> processes;
};

void analyse(const std::vector<std::string> &lines, Result &result) {
    for (auto && line: lines){
        if ((line[0] != '>' || line[1] != 'R') && (line[0] != ' ' || line[1] == ' ')) {
            continue;
        }
        if (line.size() < 50) {
            continue;
        }
        auto pid_str = line.substr(18, 9);
        auto si = pid_str.find_first_not_of(' ');
        if (pid_str[si] < 48 || pid_str[si] > 57) {
            continue;
        }
        auto pid = std::stoi(pid_str.substr(si), nullptr, 10);
        long nr_sw;
        if (line[40] == ' ') {
            nr_sw = std::stol(line.substr(41, 9), nullptr, 10);
        } else {
            nr_sw = std::stol(line.substr(42, 9), nullptr, 10);
        }
        if (result.exists(pid)) {
            result[pid]->add(nr_sw);
        } else {
            auto process = new Process(pid, line.substr(2, 15), nr_sw);
            result.add_process(process);
        }
    }
}

int main(int argc, char const *argv[])
{
    int count = 10;
    int topN = 10;
    if (argc > 1) {
        topN = std::stoi(argv[1], nullptr, 10);
    }
    if (argc > 2) {
        count = std::stoi(argv[2], nullptr, 10);
    }
    std::cout << count << " seconds" << std::endl;
    std::cout << "top" << topN << std::endl;

    std::chrono::duration<double> d(0);
    Result result;
    while (count -- > 0) {
        auto lines(read_proc_file());
        analyse(lines, result);
        std::this_thread::sleep_for(std::chrono::duration<double>(1.0));
    }
    result.print_topN(topN);
    return 0;
}
