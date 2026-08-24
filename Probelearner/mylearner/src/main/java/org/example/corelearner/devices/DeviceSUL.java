package org.example.corelearner.devices;

import org.example.corelearner.core.CoreSUL;

public abstract class DeviceSUL {
    CoreSUL coreSUL;

    public DeviceSUL(CoreSUL coreSUL) {
        this.coreSUL = coreSUL;
    }

    public abstract void pre();

    public abstract void post();

    public abstract String step(String symbol);
}
