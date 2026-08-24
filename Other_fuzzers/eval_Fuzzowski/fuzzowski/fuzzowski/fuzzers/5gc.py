from .ifuzzer import IFuzzer
from binascii import hexlify, unhexlify
from fuzzowski import Session
from fuzzowski.mutants.spike import *


class CoreFuzzer(IFuzzer):
    """
    Example 5GC fuzzer
    """

    name = '5gc'

    @staticmethod
    def get_requests() -> List[callable]:
        return [
            CoreFuzzer.reg_req, CoreFuzzer.reg_comp, CoreFuzzer.dereg_req, CoreFuzzer.dereg_accept, 
            CoreFuzzer.serv_req, CoreFuzzer.conf_update_comp, CoreFuzzer.auth_resp, 
            CoreFuzzer.auth_fail, CoreFuzzer.id_resp, CoreFuzzer.sec_mod_comp, 
            CoreFuzzer.sec_mod_rej, CoreFuzzer.gmm_stat, CoreFuzzer.ul_nas_transport,
            CoreFuzzer.pdu_session_est_req, CoreFuzzer.pdu_session_auth_complete,
            CoreFuzzer.pdu_session_mod_req, CoreFuzzer.pdu_session_mod_complete,
            CoreFuzzer.pdu_session_mod_reject, CoreFuzzer.pdu_session_release_req, 
            CoreFuzzer.pdu_session_release_complete
        ]
    
    @staticmethod
    def define_nodes(*args, **kwargs) -> None:

        def unhexlify_encoder(d):
            if len(d) % 2 != 0:
                d += b"0"
            return unhexlify(d)

        s_initialize("reg_req")
        s_static("aflnetMessage_")
        s_static("7e0041", name="header")
        with s_block("reg_req_block", encoder=hexlify):
            s_string(unhexlify("79000D0199F9070000000000000000701001002E04F0F0F0F02F020101530100"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("reg_comp")
        s_static("aflnetMessage_")
        s_static("7e0043", name="header")
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("dereg_req")
        s_static("aflnetMessage_")
        s_static("7e0045", name="header")
        with s_block("dereg_req_block", encoder=hexlify):
            s_string(unhexlify("71000D0199F907000000000000000070"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("dereg_accept")
        s_static("aflnetMessage_")
        s_static("7e0048", name="header")
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("serv_req")
        s_static("aflnetMessage_")
        s_static("7e004c", name="header")
        with s_block("serv_req_block", encoder=hexlify):
            s_string(unhexlify("170007F4000000000000"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("conf_update_comp")
        s_static("aflnetMessage_")
        s_static("7e0055", name="header")
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("auth_resp")
        s_static("aflnetMessage_")
        s_static("7e0057", name="header")
        with s_block("auth_resp_block", encoder=hexlify):
            s_string(unhexlify("2D106623B0E53AEC1C0318707EF34C8FAC92"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("auth_fail")
        s_static("aflnetMessage_")
        s_static("7e0059", name="header")
        with s_block("auth_fail_block", encoder=hexlify):
            s_string(unhexlify("6F"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("id_resp")
        s_static("aflnetMessage_")
        s_static("7e005c", name="header")
        with s_block("id_resp_block", encoder=hexlify):
            s_string(unhexlify("000D0199F907000000000000000070"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("sec_mod_comp")
        s_static("aflnetMessage_")
        s_static("7e005e", name="header")
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("sec_mod_rej")
        s_static("aflnetMessage_")
        s_static("7e005f", name="header")
        with s_block("sec_mod_rej_block", encoder=hexlify):
            s_string(unhexlify("18"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("gmm_stat")
        s_static("aflnetMessage_")
        s_static("7e0064", name="header")
        with s_block("gmm_stat_block", encoder=hexlify):
            s_string(unhexlify("6f"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("ul_nas_transport")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("000000"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionEstablishmentRequest")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("0100152E0101C1FFFF91A12801007B000780000A00000D00120181220101250908696E7465726E6574"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionAuthenticationComplete")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("000000"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionModificationRequest")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("0100042E0000C9120182220101250908696E7465726E6574"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionModificationComplete")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("0100042E0000CC1201"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionModificationCommandReject")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("0100052E0102CD6F1201"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionReleaseRequest")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("0100062E0102D159241201"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

        s_initialize("PDUSessionReleaseComplete")
        s_static("aflnetMessage_")
        s_static("7e0067", name="header")
        with s_block("ul_nas_transport_block", encoder=hexlify):
            s_string(unhexlify("0100042E0000D41201"), name="pdu", max_len=1000)
        s_static(b":")
        s_group(b"1", values=[b"1", b"2", b"3"], name="flag")
        s_static(b":")
        s_group(b"0", values=[f"{n}".encode() for n in range(16)], name="sht")

        # --------------------------------------------------------------- #

    @staticmethod
    def reg_req(session: Session) -> None:
        session.connect(s_get("reg_req"))

    @staticmethod
    def reg_comp(session: Session) -> None:
        session.connect(s_get("reg_comp"))

    @staticmethod
    def dereg_req(session: Session) -> None:
        session.connect(s_get("dereg_req"))

    @staticmethod
    def dereg_accept(session: Session) -> None:
        session.connect(s_get("dereg_accept"))

    @staticmethod
    def serv_req(session: Session) -> None:
        session.connect(s_get("serv_req"))

    @staticmethod
    def conf_update_comp(session: Session) -> None:
        session.connect(s_get("conf_update_comp"))

    @staticmethod
    def auth_resp(session: Session) -> None:
        session.connect(s_get("auth_resp"))

    @staticmethod
    def auth_fail(session: Session) -> None:
        session.connect(s_get("auth_fail"))

    @staticmethod
    def id_resp(session: Session) -> None:
        session.connect(s_get("id_resp"))

    @staticmethod
    def sec_mod_comp(session: Session) -> None:
        session.connect(s_get("sec_mod_comp"))

    @staticmethod
    def sec_mod_rej(session: Session) -> None:
        session.connect(s_get("sec_mod_rej"))

    @staticmethod
    def gmm_stat(session: Session) -> None:
        session.connect(s_get("gmm_stat"))

    @staticmethod
    def ul_nas_transport(session: Session) -> None:
        session.connect(s_get("ul_nas_transport"))

    @staticmethod
    def pdu_session_est_req(session: Session) -> None:
        session.connect(s_get("PDUSessionEstablishmentRequest"))

    @staticmethod
    def pdu_session_auth_complete(session: Session) -> None:
        session.connect(s_get("PDUSessionAuthenticationComplete"))

    @staticmethod
    def pdu_session_mod_req(session: Session) -> None:
        session.connect(s_get("PDUSessionModificationRequest"))

    @staticmethod
    def pdu_session_mod_complete(session: Session) -> None:
        session.connect(s_get("PDUSessionModificationComplete"))

    @staticmethod
    def pdu_session_mod_reject(session: Session) -> None:
        session.connect(s_get("PDUSessionModificationCommandReject"))

    @staticmethod
    def pdu_session_release_req(session: Session) -> None:
        session.connect(s_get("PDUSessionReleaseRequest"))

    @staticmethod
    def pdu_session_release_complete(session: Session) -> None:
        session.connect(s_get("PDUSessionReleaseComplete"))


