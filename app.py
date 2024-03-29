from pyteal import *
from typing import Tuple
from pytealutils.storage.blob import Blob
from pytealutils.string import encode_uvarint
import os

# Maximum number of bytes for a blob
max_bytes = 127 * 16
max_bits = max_bytes * 8

action_lookup = Bytes("lookup")
action_flip_bit = Bytes("flip_bit")

admin_addr = "PU2IEPAQDH5CCFWVRB3B5RU7APETCMF24574NA5PKMYSHM2ZZ3N3AIHJUI"
seed_amt = int(1e9)


def approval(
    admin_addr: str = admin_addr,
    seed_amt: int = seed_amt,
    tmpl_bytecode: Tuple[str, str, str] = None,
):

    seed_amt = Int(seed_amt)
    admin_addr = Addr(admin_addr)

    blob = Blob()

    # The bit index (seq) should always be the second arg
    bit_idx = Btoi(Txn.application_args[1])

    # Offset into the blob of the byte
    byte_offset = (bit_idx / Int(8)) % Int(max_bytes)

    # Offset into the byte of the bit
    bit_offset = bit_idx % Int(max_bits)

    # start index of seq ids an account is holding
    acct_seq_start = bit_idx / Int(max_bits)

    @Subroutine(TealType.bytes)
    def get_sig_address(emitter: TealType.bytes, acct_seq_start: TealType.uint64):
        return Sha512_256(
            Concat(
                Bytes("Program"),
                Bytes("base16", tmpl_bytecode[0]),
                encode_uvarint(acct_seq_start, Bytes("")),
                Bytes("base16", tmpl_bytecode[1]),
                encode_uvarint(
                    Len(emitter), Bytes("")
                ),  # First write length of bytestring encoded as uvarint
                emitter,  # Now the actual bytestring
                Bytes("base16", tmpl_bytecode[2]),
            )
        )

    @Subroutine(TealType.uint64)
    def optin():
        # Alias for readability
        algo_seed = Gtxn[0]
        optin = Gtxn[1]

        well_formed_optin = And(
            # Check that we're paying it
            algo_seed.type_enum() == TxnType.Payment,
            algo_seed.sender() == admin_addr,
            algo_seed.amount() == seed_amt,
            # Check that its an opt in to us
            optin.type_enum() == TxnType.ApplicationCall,
            optin.on_completion() == OnComplete.OptIn,
            # Not strictly necessary since we wouldn't be seeing this unless it was us, but...
            optin.application_id() == Global.current_application_id(),
        )

        return Seq(
            # Make sure its a valid optin
            Assert(well_formed_optin),
            # Init by writing to the full space available for the sender (Int(0))
            blob.zero(Int(0)),
            # we gucci
            Int(1),
        )

    @Subroutine(TealType.uint64)
    def lookup():
        return GetBit(blob.get_byte(Int(1), byte_offset), bit_offset % Int(8))

    @Subroutine(TealType.uint64)
    def flip_bit():
        b = ScratchVar()
        bit_byte_offset = bit_idx % Int(8)
        return Seq(
            Assert(
                Txn.accounts[1]
                == get_sig_address(Txn.application_args[2], acct_seq_start)
            ),
            b.store(blob.get_byte(Int(1), byte_offset)),
            blob.set_byte(
                Int(1),
                byte_offset,
                SetBit(
                    b.load(),
                    bit_byte_offset,
                    GetBit(BitwiseNot(b.load()), bit_byte_offset),
                ),
            ),
            Int(1),
        )

    router = Cond(
        [Txn.application_args[0] == action_flip_bit, flip_bit()],
        [Txn.application_args[0] == action_lookup, lookup()],
    )

    return Cond(
        [Txn.application_id() == Int(0), Int(1)],
        [Txn.on_completion() == OnComplete.DeleteApplication, Int(0)],
        [Txn.on_completion() == OnComplete.UpdateApplication, Int(1)],
        [Txn.on_completion() == OnComplete.CloseOut, Int(1)],
        [Txn.on_completion() == OnComplete.OptIn, optin()],
        [Txn.on_completion() == OnComplete.NoOp, router],
    )


def clear():
    return Return(Int(1))


def get_approval_src(**kwargs):
    return compileTeal(
        approval(**kwargs), mode=Mode.Application, version=5, assembleConstants=True
    )


def get_clear_src():
    return compileTeal(
        clear(), mode=Mode.Application, version=5, assembleConstants=True
    )


if __name__ == "__main__":
    path = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(path, "approval.teal"), "w") as f:
        f.write(get_approval_src())

    with open(os.path.join(path, "clear.teal"), "w") as f:
        f.write(get_clear_src())
