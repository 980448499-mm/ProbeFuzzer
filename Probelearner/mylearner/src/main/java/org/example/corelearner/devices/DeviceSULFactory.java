package org.example.corelearner.devices;

import org.example.corelearner.core.CoreSUL;

public class DeviceSULFactory {
    public static DeviceSUL getSULByDevice(String deviceName, CoreSUL coreSUL) {
            return new Open5GSSUL(coreSUL);
    }
}
