"""Spike 06: Verify cclib parsing (especially atomspins) on open-shell Gaussian16 output."""

import urllib.request
from pathlib import Path

import cclib
from pymatgen.io.gaussian import GaussianOutput

SAMPLE_URL = (
    "https://raw.githubusercontent.com/cclib/cclib/master/"
    "data/Gaussian/basicGaussian16/dvb_un_sp.log"
)


def main() -> None:
    out_dir = Path(__file__).parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "dvb_un_sp.log"
    if not log_path.exists():
        print(f"Downloading {SAMPLE_URL} ...")
        urllib.request.urlretrieve(SAMPLE_URL, log_path)

    data = cclib.io.ccread(str(log_path))
    assert data is not None, "cclib failed to parse log"

    print("natom:", data.natom)
    print("charge:", data.charge, "mult:", data.mult)
    print("scfenergies (eV):", data.scfenergies)
    print("moenergies len (spin channels):", len(data.moenergies))
    print("homos:", data.homos)
    print("atomcharges keys:", list(getattr(data, "atomcharges", {}).keys()))
    print("atomspins keys:", list(getattr(data, "atomspins", {}).keys()))

    assert len(data.moenergies) == 2, "Expected 2 spin channels (alpha, beta)"
    assert len(data.homos) == 2
    assert hasattr(data, "atomspins") and "mulliken" in data.atomspins
    mulliken_spins = data.atomspins["mulliken"]
    print("mulliken spin sum:", float(sum(mulliken_spins)), "first 5:", mulliken_spins[:5])

    # Cross-check with pymatgen GaussianOutput
    gout = GaussianOutput(str(log_path))
    print("pymatgen normal_termination:", gout.properly_terminated)
    print("pymatgen final_energy (Ha):", gout.final_energy)
    assert gout.properly_terminated

    print("PASS: spike_06_cclib_parser")


if __name__ == "__main__":
    main()
