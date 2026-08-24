#!/usr/bin/env python3

from boofuzz import *


def main():
    """
    This example is a very simple FTP fuzzer. It uses no process monitory
    (procmon) and assumes that the FTP server is already running.
    """
    session = Session(target=Target(connection=TCPSocketConnection("127.0.0.1", 24301)))

    define_proto(session=session)

    session.fuzz()


def define_proto(session):

    req = Request("NASMessage", children=(
        Block(name="PDU", children=(
            String(name="NAS-PDUheaderBytes", default_value="7E00", fuzzable=False), #7e00 as a NAS msg indicator
            Group(name="Msg-group", values=["41", "43", "45", "48", "4C", "55", "57", "59", "5C", "5E", "5F", "64", "67"]), # Target on fuzzing all msg type
            Group(name="MsgPDU", values=["79000D0199F9070000000000000000701001002E04F0F0F0F02F020101530100","71000D0199F907000000000000000070", "170007F4000000000000", "6F", "000D0199F907000000000000000070", "18", "6F", "67000000", "000000", "", "", "2D106623B0E53AEC1C0318707EF34C8FAC92", "0100152E0101C1FFFF91A12801007B000780000A00000D00120181220101250908696E7465726E6574", "0100042E0000C9120182220101250908696E7465726E6574", "0100042E0000CC1201", "0100052E0102CD6F1201", "0100062E0102D159241201", "0100042E0000D41201"]),
        )),
        Delim(name="colon-1", default_value=":", fuzzable=False),
        Block(name="flag", children=(
            Group(name="flag1", values=["1", "2", "3"]),  # Target on fuzzing all msg type
        )),
        Delim(name="colon-2", default_value=":", fuzzable=False),
        Block(name="Headertype", children=(
            Group(name="header", values=["0", "1", "2", "3", "4","5","6","7","8","9","10","11","12","13","14","15"]),  # msg header
        )),
    ))


    session.connect(req)


if __name__ == "__main__":
    main()
