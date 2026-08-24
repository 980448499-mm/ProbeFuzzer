package org.example.corelearner.core;

/*
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */


import de.learnlib.api.SUL;
import net.automatalib.words.impl.SimpleAlphabet;
import org.example.corelearner.StateLearnerSUL;
import org.example.corelearner.devices.DeviceSUL;
import org.example.corelearner.devices.DeviceSULFactory;

import java.io.*;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static java.lang.Thread.sleep;


public class CoreSUL implements StateLearnerSUL<String, String> {
    private static final String[] WIN_RUNTIME = {"cmd.exe", "/C"};
    private static final String[] OS_LINUX_RUNTIME = {"/bin/bash", "-l", "-c"};
    
    private final DeviceSUL deviceSUL;
    public Socket ue_socket;
    public BufferedWriter ue_out;
    public BufferedReader ue_in;
    public SimpleAlphabet<String> alphabet;
    public static CoreConfig config;
    public static int IMSI_OFFSET = 0;

    public CoreSUL(CoreConfig config) {
            CoreSUL.config = config;
        alphabet = new SimpleAlphabet<String>(Arrays.asList(config.alphabet.split(" ")));

        System.out.println("Starting Core & gNodeB & UE");
        start_core_enb_ue();
        System.out.println("Finished starting up Core & gNodeB");
        init_ue_con();
        System.out.println("Done with initializing the connection with UE, gNodeB, and Core.");

        this.deviceSUL = DeviceSULFactory.getSULByDevice(config.device, this);
        if (deviceSUL == null) {
            System.out.println("config.device is wrong, or not handled in Device_SUL_Factory. Exiting...");
            System.exit(1);
        }
    }

    public static void start_gNodeB() {
        runProcess(false, "echo \"" + config.root_password + "\"  | sudo -S " + config.ueransim_path + "/build/nr-gnb -c " + config.ueransim_path + "/config/open5gs-gnb.yaml > ./gnb.log");

    }

    public static void start_core() {
        runProcess(false, "echo \"" + config.root_password + "\" | sudo -S ./scripts/start_core.sh > core.log");
    }

    public static void start_ue(int offset) {
        if (offset < 9)
            runProcess(false, "echo \"" + config.root_password + "\" | sudo -S " + config.ueransim_path + "/build/nr-ue -c " + config.ueransim_path + "/config/open5gs-ue.yaml -i imsi-99970000000000" + (1 + offset) + "> ./ue.log");
        else
            runProcess(false, "echo \"" + config.root_password + "\" | sudo -S " + config.ueransim_path + "/build/nr-ue -c " + config.ueransim_path + "/config/open5gs-ue.yaml -i imsi-9997000000000" + (1 + offset) + "> ./ue.log");
    }

    public static void kill_gNodeb() {
        runProcess(false, "echo \"" + config.root_password + "\" | sudo -S ./scripts/kill_gnb.sh");
    }

    public static void kill_core() {
        runProcess(false, "echo \"" + config.root_password + "\" | sudo -S ./scripts/kill_core.sh");
    }

    public static void kill_ue() {
        runProcess(false, "echo \"" + config.root_password + "\" | sudo -S ./scripts/kill_ue.sh");
    }

    public static void runProcess(boolean isWin, String... command) {
        String[] allCommand;
        try {
            if (isWin) {
                allCommand = concat(WIN_RUNTIME, command);
            } else {
                allCommand = concat(OS_LINUX_RUNTIME, command);
            }
            ProcessBuilder pb = new ProcessBuilder(allCommand);
            pb.redirectErrorStream(true);
            Process p = pb.start();

        } catch (IOException e) {
            System.out.println("ERROR: " + Arrays.toString(command) + " is not running after invoking script");
            System.out.println("Attempting again...");
            e.printStackTrace();
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    private static <T> T[] concat(T[] first, T[] second) {
        T[] result = Arrays.copyOf(first, first.length + second.length);
        System.arraycopy(second, 0, result, first.length, second.length);
        return result;
    }

    public SimpleAlphabet<String> getAlphabet() {
        return alphabet;
    }

    public SUL<String, String> fork() throws UnsupportedOperationException {
        throw new UnsupportedOperationException("Cannot fork SocketSUL");
    }

    public void post() {
        deviceSUL.post();
    }

    public String step(String symbol) {
        return deviceSUL.step(symbol);
    }

    public void pre() {
        deviceSUL.pre();
        try {
            sleep(100);
            System.out.println("Connecting to ue..");
            ue_socket = new Socket(config.ue_controller_ip_address, config.ue_port);
            ue_socket.setTcpNoDelay(true);
            ue_out = new BufferedWriter(new OutputStreamWriter(ue_socket.getOutputStream()));
            ue_in = new BufferedReader(new InputStreamReader(ue_socket.getInputStream()));
            try {
                ue_socket.setSoTimeout(5000);
                if (ue_in.readLine().equals("DONE")) {
                    System.out.println("Connected with UE.");
                }
            } catch (SocketTimeoutException e) {
                System.out.println("Timeout occurred for UE");
                IMSI_OFFSET = 20;
                ue_socket.close();
                pre();
            }
        } catch (Exception e) {
//            e.printStackTrace();
            System.out.println("pre socket wrong!");
            IMSI_OFFSET = 20;
            pre();
        }
    }

    /**
     * Methods to kill and restart Core and gNB
     */

    public void start_core_enb_ue() {
        // kill and start the processes
        try {
            kill_gNodeb();
            kill_ue();
            sleep(500);
            kill_core();
            sleep(500);
            start_core();
            sleep(5000);
            start_gNodeB();
            sleep(500);
            start_ue(0);
            sleep(500);
        } catch (Exception e) {
            e.printStackTrace();
        }
    }

    public void init_ue_con() { //state learner connect with UE
        try {
            System.out.println("Connecting to ue..");
            ue_socket = new Socket(config.ue_controller_ip_address, config.ue_port);
            ue_socket.setTcpNoDelay(true);
            ue_out = new BufferedWriter(new OutputStreamWriter(ue_socket.getOutputStream()));
            ue_in = new BufferedReader(new InputStreamReader(ue_socket.getInputStream()));
            System.out.println("Connected with UE.");


            String result = "";
            try {
                sleep(1000);
                ue_out.write("Hello\n");
                ue_out.flush();
                String result_core = ue_in.readLine();
                System.out.println("Received = " + result_core);
            } catch (Exception e) {
                e.printStackTrace();
                start_core_enb_ue();
                init_ue_con();
            }
            sleep(1000);
        } catch (Exception e) {
            e.printStackTrace();
            start_core_enb_ue();
            init_ue_con();
        }
        System.out.println("Connected to ue.");

    }

    public void kill_process(String path, String nameOfProcess) {
        ProcessBuilder pb = new ProcessBuilder(path);
        Process p;
        try {
            p = pb.start();
        } catch (IOException e) {
            e.printStackTrace();
        }

        System.out.println("Killed " + nameOfProcess);
        System.out.println("Waiting a second");
        try {
            TimeUnit.SECONDS.sleep(2);
        } catch (InterruptedException e) {
            e.printStackTrace();
        }

        String line;
        try {
            Process temp = Runtime.getRuntime().exec("pidof " + nameOfProcess);
            BufferedReader input = new BufferedReader(new InputStreamReader(temp.getInputStream()));
            line = input.readLine();
            if (line != null) {
                System.out.println("ERROR: " + nameOfProcess + " is still running after invoking kill script");
                System.out.println("Attempting termination again...");
                kill_process(path, nameOfProcess);
            }
        } catch (Exception e) {
            e.printStackTrace();
        }

        System.out.println(nameOfProcess + " has been killed");
    }

    private void start_process(String path, String nameOfProcess) {
        ProcessBuilder pb = new ProcessBuilder(path);
        Process p;
        try {
            p = pb.start();
            System.out.println(nameOfProcess + " process has started");
            System.out.println("Waiting a second");
            TimeUnit.SECONDS.sleep(2);
        } catch (IOException e) {
            System.out.println("IO Exception");
            System.out.println("ERROR: " + nameOfProcess + " is not running after invoking script");
            System.out.println("Attempting again...");
            start_process(path, nameOfProcess);
            e.printStackTrace();
        } catch (InterruptedException e) {
            System.out.println("Timer Exception");
            System.out.println("ERROR: " + nameOfProcess + " is not running after invoking script");
            System.out.println("Attempting again...");
            start_process(path, nameOfProcess);
            e.printStackTrace();
        }


        String line;
        try {
            Process temp = Runtime.getRuntime().exec("pidof " + nameOfProcess);
            BufferedReader input = new BufferedReader(new InputStreamReader(temp.getInputStream()));

            line = input.readLine();
            if (line == null) {
                System.out.println("ERROR: " + nameOfProcess + " is not running after invoking script");
                System.out.println("Attempting again...");
                start_process(path, nameOfProcess);
            }
        } catch (IOException e) {
            e.printStackTrace();
        }

        System.out.println(nameOfProcess + " has started...");
    }
}
