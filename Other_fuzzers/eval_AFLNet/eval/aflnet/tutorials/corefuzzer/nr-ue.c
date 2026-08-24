#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <string.h>

#define OPEN5GS_PATH "/corefuzzer_deps/open5gs"
#define UERANSIM_PATH "/corefuzzer_deps/ueransim"
#define IMSI_OFFSET ".imsi_offset"
#define IMSI_OFFSET_MAX 10000

int ue_pid = -1;

void kill_ue() {
    if (ue_pid == -1) {
        system("pkill -2 -f nr-ue");
    } else {
        kill(ue_pid, SIGINT);
        int status;
        waitpid(ue_pid, &status, 0);
    }
}

void kill_core() {
    system("pkill -2 -f 5gc");
    system("pkill -2 -f open5gs-nrfd");
    system("pkill -2 -f open5gs-scpd");
    system("pkill -2 -f open5gs-upfd");
    system("pkill -2 -f open5gs-smfd");
    system("pkill -2 -f open5gs-amfd");
    system("pkill -2 -f open5gs-ausfd");
    system("pkill -2 -f open5gs-udmd");
    system("pkill -2 -f open5gs-pcfd");
    system("pkill -2 -f open5gs-nssfd");
    system("pkill -2 -f open5gs-bsfd");
    system("pkill -2 -f open5gs-udrd");
}

void kill_gnb() {
    system("pkill -2 -f nr-gnb");
}

void start_gnb() {
    system("nr-gnb -c " UERANSIM_PATH "/config/open5gs-gnb.yaml");
}

void start_core() {
    system("5gc -c " OPEN5GS_PATH "/build/configs/sample.yaml");
}

void start_ue(unsigned long long int imsi_offset) {
    printf("IMSI offset = %llu\n", imsi_offset);
    imsi_offset = imsi_offset % 10000;
    int child_pid = fork();
    if (child_pid < 0) {
        fprintf(stderr, "fork failed\n");
        exit(1);
    }
    if (child_pid == 0) {
        char imsi_arg[21] = "imsi-999700000";
        char temp_arg[21];
        unsigned long long int imsi = 000001 + imsi_offset;
        sprintf(temp_arg, "%06llu", imsi);
        strcat(imsi_arg, temp_arg);
        printf("Generated IMSI : %s\n", imsi_arg);
        char * args[] = {
            "nr-ue",
            "-c",
            UERANSIM_PATH "/config/open5gs-ue.yaml",
            "-i",
            imsi_arg,
            NULL
        };
        execv("/usr/bin/nr-ue", args);
    }

    ue_pid = child_pid;
}

void update_imsi_offset(unsigned long long int offset) {
    FILE *file = fopen(IMSI_OFFSET, "w");
    if (file == NULL) {
        return;
    }
    fprintf(file, "%lld", offset);
    fclose(file);
}

unsigned long long int get_imsi_offset() {
    FILE *file = fopen(IMSI_OFFSET, "r");
    unsigned long long int offset;
    if (file == NULL) {
        return 0;
    }
    fscanf(file, "%lld", &offset);
    fclose(file);
    return offset;
}

static void signal_handler(int num) {
    if (num == SIGINT || num == SIGTERM) {
        if (ue_pid != -1)
            kill(ue_pid, SIGINT);
        exit(0);
    }
}

void setup_signal_handlers(void) {

  struct sigaction sa;

  sa.sa_handler   = NULL;
  sa.sa_flags     = SA_RESTART;
  sa.sa_sigaction = NULL;

  sigemptyset(&sa.sa_mask);

  sa.sa_handler = signal_handler;
  sigaction(SIGINT, &sa, NULL);
  sigaction(SIGTERM, &sa, NULL);
}

int main(int argc, char **argv) {
    setup_signal_handlers();

    if (access(IMSI_OFFSET, F_OK) != 0) {
        update_imsi_offset(0);
    }

    unsigned long long int imsi_offset = get_imsi_offset();
    
    if (imsi_offset > IMSI_OFFSET_MAX) {
        remove(IMSI_OFFSET);
        update_imsi_offset(0);
    }

    start_ue(imsi_offset);

    if (imsi_offset == IMSI_OFFSET_MAX) {
        // kill_gnb();
        // kill_core();
        update_imsi_offset(0);
        // start_core();
        // start_gnb();
    } else {
        update_imsi_offset(imsi_offset + 1);
    }

    int status;
    waitpid(ue_pid, &status, 0);

    return 0;
}