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


import org.example.corelearner.LearningConfig;

import java.io.IOException;

public class CoreConfig extends LearningConfig {
    public String alphabet;
    public String hostname;
    public String ue_controller_ip_address;
    public int ue_port;
    public String ueransim_path;
    public String core_path;
    public String root_password;

    public boolean combine_query;
    public String delimiter_input;
    public String delimiter_output;

    public CoreConfig(String filename) throws IOException {
        super(filename);
    }

    public CoreConfig(LearningConfig config) {
        super(config);
    }

    @Override
    public void loadProperties() {
        super.loadProperties();

        if (properties.getProperty("alphabet") != null)
            alphabet = properties.getProperty("alphabet");

        if (properties.getProperty("hostname") != null)
            hostname = properties.getProperty("hostname");

        if (properties.getProperty("ue_controller_ip_address") != null)
            ue_controller_ip_address = properties.getProperty("ue_controller_ip_address");

        if (properties.getProperty("ue_port") != null)
            ue_port = Integer.parseInt(properties.getProperty("ue_port"));

        if (properties.getProperty("combine_query") != null)
            combine_query = Boolean.parseBoolean(properties.getProperty("combine_query"));
        else
            combine_query = false;

        if (properties.getProperty("delimiter_input") != null)
            delimiter_input = properties.getProperty("delimiter_input");
        else
            delimiter_input = ";";

        if (properties.getProperty("delimiter_output") != null)
            delimiter_output = properties.getProperty("delimiter_output");
        else
            delimiter_output = ";";
        
        if (properties.getProperty("ueransim_path") != null)
            ueransim_path = properties.getProperty("ueransim_path");
        if (properties.getProperty("core_path") != null)
            core_path = properties.getProperty("core_path");
        if (properties.getProperty("root_password") != null)
            root_password = properties.getProperty("root_password");
    }
}