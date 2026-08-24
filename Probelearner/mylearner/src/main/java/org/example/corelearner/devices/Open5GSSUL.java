package org.example.corelearner.devices;

import org.example.corelearner.core.CoreConfig;
import org.example.corelearner.core.CoreSUL;

import java.io.IOException;
import java.net.SocketException;
import java.net.SocketTimeoutException;
import java.util.Objects;

import static java.lang.Thread.sleep;
import static org.example.corelearner.core.CoreSUL.*;

public class Open5GSSUL extends DeviceSUL {
    public Open5GSSUL(CoreSUL coreSUL) {
        super(coreSUL);
    }

    @Override
    public void pre() {
        System.out.println("---- Starting RESET ----");
        try {
            runProcess(false, CoreSUL.config.ueransim_path + "/build/nr-cli UERANSIM-gnb-999-70-1 --exec \"ue-release 1\"");
            sleep(250);
            kill_ue();
            sleep(500);
            kill_gNodeb();
            sleep(500);
            if (IMSI_OFFSET >= 20)
            {
                kill_core();
                sleep(1000);
                start_core();
                sleep(5000);
                IMSI_OFFSET = 0;
            }
            start_gNodeB();
            sleep(500);
            start_ue(IMSI_OFFSET);
            sleep(500);
            IMSI_OFFSET++;
        } catch (Exception e) {
            System.out.println("pre sleep error!");
        }

    }

    @Override
    public void post() {}

    @Override
    public String step(String symbol) {
        try {
            sleep(500);
        } catch (InterruptedException e) {
            System.out.println("sleep error!");
        }

        int socket_wait_time = 1000;
        //If it is the first message, set a longer time for timeout.
        String result = null; // return value for step function

        try {
            if (symbol.startsWith("registrationRequest")) {
                System.out.println("Log executor: sending registrationRequest.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("registrationComplete")) {
                System.out.println("Log executor: sending registrationComplete.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("deregistrationRequest")) {
                System.out.println("Log executor: sending deregistrationRequest.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("serviceRequest")) {
                runProcess(false, config.ueransim_path + "/build/nr-cli UERANSIM-gnb-999-70-1 --exec \"ue-release 1\"");
                sleep(500);
                System.out.println("Log executor: sending serviceRequest.");
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("securityModeReject")) {
                System.out.println("Log executor: sending securityModeReject.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("authenticationResponse")) {
                System.out.println("Log executor: sending authenticationResponse.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("authenticationFailure")) {
                System.out.println("Log executor: sending authenticationFailure.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("deregistrationAccept")) {
                System.out.println("Log executor: sending deregistrationAccept.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("securityModeComplete")) {
                System.out.println("Log executor: sending securityModeComplete.");
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("identityResponse")) {
                System.out.println("Log executor: sending identityResponse.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("gmmStatus")) {
                System.out.println("Log executor: sending gmmStatus.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("configurationUpdateComplete")) {
                System.out.println("Log executor: sending configurationUpdateComplete.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            } else if (symbol.startsWith("ulNasTransport")) {
                System.out.println("Log executor: sending ulNasTransport.");
                coreSUL.ue_socket.setSoTimeout(socket_wait_time);
                coreSUL.ue_out.write(symbol);
                coreSUL.ue_out.flush();
            }

        } catch (SocketTimeoutException e) {
            System.out.println("Timeout occured for " + symbol);
            return "null_action";
        } catch (SocketException e) {
            System.out.println("socketException " + symbol);
            return "null_action";
        } catch (Exception e) {
            e.printStackTrace();
            System.exit(1);
        }

        while (result == null || result.contains("dlNasTransport")) {
            try {
                System.out.println("Reading from ue");
                result = coreSUL.ue_in.readLine();
                System.out.println("Log executor: received(raw) " + result + " from rrc.");
            } catch (SocketTimeoutException e) {
                System.out.println("Timeout occured for " + symbol);
                return "null_action";
            } catch (Exception e) {
                e.printStackTrace();
                System.exit(1);
            }
            if (result == null)
                result = "null_action";
            if (result.equals("dlNasTransport"))
                System.out.println("Get dlNasTransport, read next message..");
        }

        System.out.println("####" + symbol + "/" + result + "####");

        return result;

    }//end for step

}
