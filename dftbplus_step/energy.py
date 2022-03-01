# -*- coding: utf-8 -*-

"""Setup DFTB+"""

try:
    import importlib.metadata as implib
except Exception:
    import importlib_metadata as implib
import json
import logging
from pathlib import Path

import dftbplus_step
import seamm
import seamm.data
from seamm_util import Q_, units_class, element_data
import seamm_util.printing as printing
from seamm_util.printing import FormattedText as __

from .base import DftbBase


logger = logging.getLogger(__name__)
job = printing.getPrinter()
printer = printing.getPrinter("DFTB+")


class Energy(DftbBase):
    def __init__(
        self, flowchart=None, title="Single-Point Energy", extension=None, logger=logger
    ):
        """Initialize the node"""

        logger.debug("Creating Energy {}".format(self))

        super().__init__(flowchart=flowchart, title=title, extension=extension)

        self.parameters = dftbplus_step.EnergyParameters()

        self.description = ["Energy of DFTB+"]

    @property
    def header(self):
        """A printable header for this section of output"""
        return "Step {}: {}".format(".".join(str(e) for e in self._id), self.title)

    @property
    def version(self):
        """The semantic version of this module."""
        return dftbplus_step.__version__

    @property
    def git_revision(self):
        """The git version of this module."""
        return dftbplus_step.__git_revision__

    def description_text(self, P=None):
        """Prepare information about what this node will do"""
        if not P:
            P = self.parameters.values_to_dict()

        if P["SCC"] == "No" and not self.is_expr(P["SCC"]):
            text = "Doing a non-self-consistent calculation."
        else:
            text = (
                "Doing a self-consistent charge calculation with a convergence"
                f" criterion of {P['SCCTolerance']} charge units and a limit "
                f"of {P['MaxSCCIterations']} iterations."
            )
            third_order = P["ThirdOrder"]
            if self.is_expr(third_order):
                text += (
                    " Whether to do a 3rd order calculation and if so, "
                    f"what type, will be determined by {third_order}."
                )
            elif third_order == "Default for parameters":
                text += (
                    " Whether to do a 3rd order calculation and if so, "
                    "what type, will be determined by the parameter set used."
                )
            elif third_order == "Partial":
                text += (
                    " The older style 3rd order calculation with just on-site "
                    "elements will be used. This should be used only for "
                    "compatibility."
                )
            elif third_order == "Full":
                text += " This is a full 3rd order calculation."

            hcorrection = P["HCorrection"]
            if self.is_expr(hcorrection):
                text += (
                    " Whether to correct the hydrogen interactions will be "
                    f"determined by {hcorrection}."
                )
            elif hcorrection == "Default for parameters":
                text += (
                    " Whether and how to correct interactions with hydrogen "
                    "atoms will be determined by the parameter set used."
                )
            elif hcorrection == "Damping":
                text += (
                    " Interactions with hydrogen atoms will be corrected "
                    "using damping with an exponent of "
                    f"{P['Damping Exponent']}."
                )
            elif hcorrection == "DFTB3-D3H5":
                text += (
                    " Interactions with hydrogen atoms will be corrected "
                    "using the D3H5 method."
                )

        kmethod = P["k-grid method"]
        if kmethod == "grid spacing":
            text += (
                " If the system is periodic the integration will use a"
                f" Monkhorst-Pack grid with a spacing of {P['k-spacing']}."
            )
        elif kmethod == "supercell folding":
            text += (
                " If the system is periodic, the integration will use a"
                f" Monkhorst-Pack {P['na']} x{P['nb']} x{P['nc']} grid."
            )

        return self.header + "\n" + __(text, indent=4 * " ").__str__()

    def get_input(self):
        """Get the input for an initialization calculation for DFTB+"""

        # Create the directory
        directory = Path(self.directory)
        directory.mkdir(parents=True, exist_ok=True)

        P = self.parameters.current_values_to_dict(
            context=seamm.flowchart_variables._data
        )

        # Have to fix formatting for printing...
        PP = dict(P)
        for key in PP:
            if isinstance(PP[key], units_class):
                PP[key] = "{:~P}".format(PP[key])

        # Set up the description.
        self.description = []
        self.description.append(__(self.description_text(PP), **PP, indent=self.indent))

        # Determine the input and as we do so, replace any default values
        # in PP so that we print what is actually done

        dataset = self.parent._dataset
        parameter_set = self.parent._hamiltonian
        model, parameter_set_name = parameter_set.split(" - ", 1)

        if model == "DFTB":
            if "defaults" in dataset:
                all_defaults = {**dataset["defaults"]}
            else:
                all_defaults = {}
            if self.parent._subset is not None:
                subset = self.parent._subset
                if "defaults" in subset:
                    all_defaults.update(subset["defaults"])

            if "Energy" in all_defaults and "SCC" in all_defaults["Energy"]:
                defaults = all_defaults["Energy"]["SCC"]
            else:
                defaults = {}

            # template
            result = {
                "Analysis": {
                    "CalculateForces": "Yes",
                },
                "Hamiltonian": {"DFTB": {}},
            }
            hamiltonian = result["Hamiltonian"]["DFTB"]

            if P["SCC"] == "Yes":
                hamiltonian["SCC"] = "Yes"
                hamiltonian["SCCTolerance"] = P["SCCTolerance"]
                hamiltonian["MaxSCCIterations"] = P["MaxSCCIterations"]
                hamiltonian["ShellResolvedSCC"] = P["ShellResolvedSCC"].capitalize()

                third_order = P["ThirdOrder"]
                if third_order == "Default for parameters":
                    if "ThirdOrder" in defaults:
                        third_order = defaults["ThirdOrder"]
                        PP["ThirdOrder"] = defaults["ThirdOrder"]
                    else:
                        third_order = "No"
                        PP["ThirdOrder"] = "No"
                if third_order == "Full":
                    hamiltonian["ThirdOrderFull"] = "Yes"
                elif third_order == "Partial":
                    hamiltonian["ThirdOrder"] = "Yes"
                elif third_order == "No":
                    hamiltonian["ThirdOrder"] = "No"
                else:
                    raise RuntimeError(f"Don't recognize ThirdOrder = '{third_order}'")

                hcorrection = P["HCorrection"]
                if hcorrection == "Default for parameters":
                    if "HCorrection" in defaults:
                        hcorrection = defaults["HCorrection"]["value"]
                        hamiltonian["HCorrection"] = {hcorrection: {}}
                        block = hamiltonian["HCorrection"][hcorrection]
                        PP["HCorrection"] = hcorrection
                        if hcorrection == "Damping":
                            if "Damping Exponent" in defaults["HCorrection"]:
                                damping = defaults["HCorrection"]["Damping Exponent"]
                                PP["Damping Exponent"] = damping
                            else:
                                damping = P["Damping Exponent"]
                            block["Exponent"] = damping
                    else:
                        hamiltonian["HCorrection"] = "None {}"
                        PP["HCorrection"] = "None {}"
                else:
                    hamiltonian["HCorrection"] = hcorrection
                    if hcorrection == "Damping":
                        if (
                            "HCorrection" in defaults
                            and "Damping Exponent" in defaults["HCorrection"]
                        ):
                            damping = defaults["HCorrection"]["Damping Exponent"]
                            PP["Damping Exponent"] = damping
                        else:
                            damping = P["Damping Exponent"]
                        hamiltonian["Damping Exponent"] = damping
        elif model == "xTB":
            result = {
                "Analysis": {
                    "CalculateForces": "Yes",
                },
                "Hamiltonian": {"xTB": {}},
            }
            hamiltonian = result["Hamiltonian"]["xTB"]
            hamiltonian["SCC"] = "Yes"
            hamiltonian["SCCTolerance"] = P["SCCTolerance"]
            hamiltonian["MaxSCCIterations"] = P["MaxSCCIterations"]

        system, configuration = self.get_system_configuration(None)

        # Handle charge and spin
        hamiltonian["Charge"] = configuration.charge
        multiplicity = configuration.spin_multiplicity

        print(
            f"Charge = {configuration.charge}, multiplicity = "
            f"{configuration.spin_multiplicity}"
        )

        if multiplicity == 1 and P["SpinPolarisation"] == "none":
            hamiltonian["SpinPolarisation"] = {}
        else:
            noncolinear = P["SpinPolarisation"] == "noncolinear"

            atoms = configuration.atoms
            have_spins = "spin" in atoms

            H = hamiltonian["SpinPolarisation"] = {}
            if noncolinear:
                section = H["NonColinear"] = {}
            else:
                section = H["Colinear"] = {}
                if have_spins:
                    section["InitialSpins"] = {"AllAtomSpins": [*atoms["spin"]]}
                else:
                    section["UnpairedElectrons"] = multiplicity - 1

            print(f"{P['RelaxTotalSpin']=}")

            section["RelaxTotalSpin"] = P["RelaxTotalSpin"].capitalize()

            # Get the spin constants
            package = self.__module__.split(".")[0]
            files = [
                p for p in implib.files(package) if p.name == "spin-constants.json"
            ]
            if len(files) != 1:
                raise RuntimeError(
                    "Can't find spin-constants.json file. Check the installation!"
                )
            data = files[0].read_text()
            spin_constant_data = json.loads(data)

            # First check if we have shell resolved constants or not
            spin_constants = hamiltonian["SpinConstants"] = {}
            symbols = sorted([*set(atoms.symbols)])
            dataset_name = self.parent._hamiltonian
            # e.g. "DFTB - mio"
            key = dataset_name.split(" - ")[1]
            if key in spin_constant_data:
                constants = spin_constant_data[key]
            else:
                constants = spin_constant_data["GGA"]

            # Bit of a kludgy test. If not shell-resolved there is one constant
            # per shell, i.e. 1, 2 or 3 for s, p, d. If reolved, there are 1, 4, 9.
            shell_resolved = False
            for symbol in symbols:
                if len(constants[symbol]) > 3:
                    shell_resolved = True
                    break

            if shell_resolved:
                if P["ShellResolvedSpin"] == "yes":
                    spin_constants["ShellResolvedSpin"] = "Yes"
                else:
                    spin_constants["ShellResolvedSpin"] = "No"
                    shell_resolved = False
            else:
                spin_constants["ShellResolvedSpin"] = "No"

            # And add them and the control parameters
            if shell_resolved:
                for symbol in symbols:
                    spin_constants[symbol] = (
                        "{" + " ".join([str(c) for c in constants[symbol]]) + "}"
                    )
            else:
                for symbol in symbols:
                    shells = element_data[symbol]["electron configuration"]
                    shell = shells.split()[-1]
                    print(f"{shell=}")
                    tmp = constants[symbol]
                    if "s" in shell:
                        spin_constants[symbol] = str(tmp[0])
                    elif "p" in shell:
                        if len(tmp) == 4:
                            spin_constants[symbol] = str(tmp[3])
                        elif len(tmp) == 9:
                            spin_constants[symbol] = str(tmp[4])
                        else:
                            raise RuntimeError(
                                f"Error in spin constants for {symbol}: {tmp}"
                            )
                    elif "d" in shell:
                        if len(tmp) == 9:
                            spin_constants[symbol] = str(tmp[8])
                        else:
                            raise RuntimeError(
                                f"Error in spin constants for {symbol}: {tmp}"
                            )
                    else:
                        raise RuntimeError(f"Can't handle spin constants for {symbol}")

        # Integration grid in reciprocal space
        if configuration.periodicity == 3:
            kmethod = P["k-grid method"]
            if kmethod == "grid spacing":
                lengths = configuration.cell.reciprocal_lengths()
                spacing = P["k-spacing"].to("1/Å").magnitude
                na = round(lengths[0] / spacing)
                nb = round(lengths[0] / spacing)
                nc = round(lengths[0] / spacing)
                na = na if na > 0 else 1
                nb = nb if nb > 0 else 1
                nc = nc if nc > 0 else 1
            elif kmethod == "supercell folding":
                na = P["na"]
                nb = P["nb"]
                nc = P["nc"]
            oa = 0.0 if na % 2 == 1 else 0.5
            ob = 0.0 if nb % 2 == 1 else 0.5
            oc = 0.0 if nc % 2 == 1 else 0.5
            kmesh = (
                "SupercellFolding {\n"
                f"    {na} 0 0\n"
                f"    0 {nb} 0\n"
                f"    0 0 {nc}\n"
                f"    {oa} {ob} {oc}\n"
                "}"
            )
            hamiltonian["KPointsAndWeights"] = kmesh
            self.description.append(
                __(
                    f"The mesh for the Brillouin zone integration is {na} x {nb} x {nc}"
                    f" with offsets of {oa}, {ob}, and {oc}",
                    indent=self.indent + 4 * " ",
                )
            )

        return result

    def analyze(self, indent="", data={}, out=[]):
        """Parse the output and generating the text output and store the
        data in variables for other stages to access
        """
        # Print the key results
        text = "The total energy is {total_energy:.6f} E_h."

        # Calculate the energy of formation
        if self.parent._reference_energy is not None:
            dE = data["total_energy"] - self.parent._reference_energy
            dE = Q_(dE, "hartree").to("kJ/mol").magnitude
            text += f" The calculated formation energy is {dE:.2f} kJ/mol."
            data["energy of formation"] = dE
        else:
            text += " Could not calculate the formation energy because some reference "
            text += "energies are missing."
            data["energy of formation"] = None

        # Prepare the DOS graph(s)
        wd = Path(self.directory)
        self.dos(wd / "band.out")

        printer.normal(__(text, **data, indent=self.indent + 4 * " "))

        # Put any requested results into variables or tables
        self.store_results(
            data=data,
            properties=dftbplus_step.properties,
            results=self.parameters["results"].value,
            create_tables=self.parameters["create tables"].get(),
        )
