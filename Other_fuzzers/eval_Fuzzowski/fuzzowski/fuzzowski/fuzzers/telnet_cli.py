from .ifuzzer import IFuzzer
from fuzzowski import Session
from fuzzowski.mutants.spike import *


class TelnetCLI(IFuzzer):
    '''
    Example module for fuzzing a CLI over Telnet (using the TelnetConnection Module)
    '''

    name = 'telnet_cli'

    @staticmethod
    def get_requests() -> List[callable]:
        return [TelnetCLI.commands]

    @staticmethod
    def define_nodes(*args, **kwargs) -> None:

        # s_initialize('example_command')
        # s_string(b'ping', fuzzable=False)
        # s_delim(b' ',     fuzzable=True, name='delim_space')
        # s_string(b'1.2.3.4',    fuzzable=True, name='ip')
        # s_delim(b'\r\n',     fuzzable=False)


        s_initialize('nas_msg')
        with s_block('PDU'):
            s_string(b'7E00', fuzzable=False)
            s_group(b'41', values=[b'41', b'43', b'45', b'48', b'4C', b'55', b'57', b'59', b'5C', b'5E', b'5F', b'64', b'67'])
            s_group(b'6F', values=[b'79000D0199F9070000000000000000701001002E04F0F0F0F02F020101530100', b'71000D0199F907000000000000000070', b'170007F4000000000000', b'6F', b'000D0199F907000000000000000070', b'18', b'6F', b'67000000', b'000000', b'', b'2D106623B0E53AEC1C0318707EF34C8FAC92', b'0100152E0101C1FFFF91A12801007B000780000A00000D00120181220101250908696E7465726E6574', b'0100042E0000C9120182220101250908696E7465726E6574', b'0100042E0000CC1201', b'0100052E0102CD6F1201', b'0100062E0102D159241201', b'0100042E0000D41201'])
        s_delim(value=b':', fuzzable=False)
        with s_block('flag'):
            s_group(b'1', values=[b'1', b'2', b'3'])
        s_delim(value=b':', fuzzable=False)
        with s_block('Headertype'):
         s_group(b'0', values=[b'0', b'1', b'2', b'3', b'4', b'5', b'6', b'7', b'8', b'9', b'10', b'11', b'12', b'13', b'14', b'15'])


    # --------------------------------------------------------------- #

    @staticmethod
    def commands(session: Session) -> None:
        # session.connect(s_get('example_command'))
        session.connect(s_get('nas_msg'))
