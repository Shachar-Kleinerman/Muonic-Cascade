import subprocess
import glob
import os
import re
import random
import matplotlib.pyplot as plt
import numpy as np

# True: the decays of a level include the transitions to the s and p states of the SAME shell (see create_mudirac_input)
INCLUDE_SAME_SHELL = True

# Directory where all generated MUDIRAC files and plots will be saved
OUTPUT_DIR = "simulation_outputs"
os.makedirs(OUTPUT_DIR, exist_ok=True)
try:                                    # hosting: an uploaded binary may lose its execute permission
    os.chmod("./mudirac", 0o755)
except OSError:
    pass

# Global mapping constants for quantum shells (n) and orbital angular momentum (l)
shell_letters = {
    1: "K", 2: "L", 3: "M", 4: "N", 5: "O", 6: "P", 7: "Q",
    8: "R", 9: "S", 10: "T", 11: "U", 12: "V", 13: "W", 14: "X"
}

l_symbols = ['s', 'p', 'd', 'f', 'g', 'h', 'i', 'k', 'l', 'm', 'n', 'o', 'q', 'r']


def generate_mudirac_dict(max_n=14):
    """
    Generates the mapping from physical level names (e.g., '2p_3/2', '5g_9/2')
    to MUDIRAC shorthand codes (e.g., 'L3', 'O9').
    """
    mapping = {}
    for n in range(1, max_n + 1):
        shell = shell_letters[n]
        for l in range(n):
            if l == 0:
                # l=0 --> only j = 1/2
                mapping[f"{n}s_1/2"] = f"{shell}1"
            else:
                # Lower j: j = l - 1/2 = (2l - 1)/2 --> index 2*l
                j_low = f"{2*l - 1}/2"
                mapping[f"{n}{l_symbols[l]}_{j_low}"] = f"{shell}{2*l}"

                # Higher j: j = l + 1/2 = (2l + 1)/2 --> index 2*l + 1
                j_high = f"{2*l + 1}/2"
                mapping[f"{n}{l_symbols[l]}_{j_high}"] = f"{shell}{2*l + 1}"
                
    return mapping


mudirac_dict = generate_mudirac_dict(max_n=14)

# Inverse dictionary to translate MUDIRAC codes (e.g., 'K1') back to physical level names (e.g., '1s_1/2')
inverse_mudirac_dict = {v: k for k, v in mudirac_dict.items()}

# In-memory cache to store calculated levels and avoid running MUDIRAC multiple times for the same state
live_cache = {}

# MUDIRAC energy_damp values tried (in this order) when a state does not converge. None = MUDIRAC's own default.
# energy_damp only changes how the solver iterates, not the physics (checked: converged energies agree to ~1e-9).
DAMPING_LADDER = [None, 0.3, 0.2, 0.15]

# What is tried, in this order, when MUDIRAC's solver does not give a complete result for a level. Every step changes only
# how the solver iterates (MUDIRAC keywords.pdf: max_E_iter = most iterations of the energy search, default 100 - "increase
# for slow convergences that are however progressing"; energy_damp = step damping, default 0.5), never the physics.
RETRY_STEPS = [{}, {"max_E_iter": 1000}] + [{"energy_damp": d} for d in DAMPING_LADDER if d is not None]

BOHR_FM = 52917.721067        # 1 atomic unit of length in fm (MUDIRAC writes radii in atomic units)
WF_POINTS = 400               # samples kept per radial wavefunction (uniform in r, linear interpolation of MUDIRAC's own grid)


def wf_key(element, level_name, kwargs):
    """Cache key of the wavefunction of one state: it depends on the element / isotope / physics settings only."""
    params = tuple(sorted((k, v) for k, v in kwargs.items() if k not in ("energy_damp", "output")))
    return ("WF", element, level_name, params)


def harvest_wavefunctions(input_filename, element, kwargs):
    """Reads the radial state files MUDIRAC wrote next to input_filename (output: 2) and keeps, for every state, the
    real MUDIRAC wavefunction P(r), Q(r) on WF_POINTS points in live_cache. Values are MUDIRAC's, only resampled."""
    base = os.path.splitext(input_filename)[0]
    for code, level_name in inverse_mudirac_dict.items():
        key = wf_key(element, level_name, kwargs)
        path = f"{base}.{code}.out"
        if key in live_cache or not os.path.exists(path):
            continue
        try:
            data = np.loadtxt(path, comments="#")
            with open(path) as fh:
                head = [next(fh) for _ in range(4)]
        except (ValueError, OSError, StopIteration):
            continue
        if data.ndim != 2 or data.shape[1] < 4 or len(data) < 10:
            continue
        r, p, q = data[:, 0], data[:, 2], data[:, 3]
        order = np.argsort(r)
        r, p, q = r[order], p[order], q[order]
        big = np.where(np.abs(p) > 0.005 * np.max(np.abs(p)))[0]
        r_max = r[big[-1]] * 1.25 if len(big) else r[-1]
        grid = np.linspace(0.0, min(r_max, r[-1]), WF_POINTS)
        # MUDIRAC's grid starts at a small r > 0; the wavefunction vanishes at r = 0
        p_i = np.interp(grid, r, p, left=0.0)
        q_i = np.interp(grid, r, q, left=0.0)
        m = re.search(r"E = (\S+) \+ mc\^2", head[2])
        live_cache[key] = {
            "r_fm": [float(f"{v * BOHR_FM:.6g}") for v in grid],
            "P": [float(f"{v:.6g}") for v in p_i],
            "Q": [float(f"{v:.6g}") for v in q_i],
            "E_bind_eV": float(m.group(1)) if m else None,
        }


def get_n(level_name):
    """Extracts the principal quantum number (n) from a level name (supporting n >= 10)."""
    return int(re.match(r"^(\d+)", level_name).group(1))


def create_mudirac_input(level_name, target="ALL_LOWER", verbose=True, **kwargs):
    """
    Creates a MUDIRAC input file (.in) and executes the MUDIRAC simulation.
    - By default (target='ALL_LOWER'), calculates transitions to all shells below level_name.
    - If a specific level is passed (e.g., target='1s_1/2'), calculates that single transition.
    """
    # 1. Validate that the source level exists in the dictionary
    if level_name not in mudirac_dict:
        print(f'Error: Source level "{level_name}" not found in dictionary!')
        return None

    # Translate source level from physical name (e.g., '7i_13/2') to MUDIRAC code (e.g., 'Q13')
    code = mudirac_dict[level_name]

    # 2. Determine target code: either all lower shells or a single specific target level
    if target == "ALL_LOWER":
        source_n = get_n(level_name)
        if source_n == 1:
            print("Error: Level 1s_1/2 is the ground state and has no lower levels!")
            return None

        # every state of the lower shells, plus the s and p states of the source's OWN shell. MUDIRAC itself drops the
        # lines whose energy is not positive (a state above the source), so what remains are the downward dipole
        # transitions - also those inside the shell (2s -> 2p, 4s -> 4p ... in heavy atoms, where the finite nuclear size
        # lifts the s states above the p states; the MUDIRAC paper's own gold spectrum has such lines: N3-N1, N2-N1 in
        # Fig. 7, O2-O1 and O3-O1 in the text). Same-shell lines into d, f, g ... states are not requested: they connect
        # nearly degenerate states, and measured with MUDIRAC they carry at most 0.03 % of a level's decay (uranium, the
        # heaviest case tried; < 0.005 % in lead, ~1e-14 in helium).
        lower = "K1" if source_n == 2 else f"K1:{shell_letters[source_n - 1]}{2*(source_n - 1) - 1}"
        parts = [f"{lower}-{code}"]
        if INCLUDE_SAME_SHELL:
            parts += [f"{shell_letters[source_n]}{i}-{code}" for i in (1, 2, 3) if f"{shell_letters[source_n]}{i}" != code]
        target_code = None
        xr_lines = ",".join(parts)

    elif target in mudirac_dict:
        target_code = mudirac_dict[target]
        xr_lines = f"{target_code}-{code}"

    else:
        print(f'Error: Target "{target}" not found in dictionary!')
        return None

    # 3. Sanitize level name to create a valid operating-system filename (remove '/')
    safe_name = level_name.replace("_", "-").replace("/", "_")

    # 4. Define default simulation parameters (set to maximum physical accuracy)
    element_name = kwargs.get("element", "C")
    params = {
        "element": element_name,
        "nuclear_model": "FERMI2",                  # 2-parameter Fermi nuclear charge distribution
        "uehling_correction": True,                 # QED vacuum polarization (Uehling potential)
        "electronic_config": f"[{element_name}]",   # Full ground-state electronic screening
        "reduced_mass": True,                       # Nuclear recoil via reduced mass
        "output": 1,                                # 1 = .xr.out only (fast); 2 = wavefunctions
        "verbosity": 1,
    }
    params.update(kwargs)
    params = {k: v for k, v in params.items() if v is not None}   # e.g. electronic_config=None: no electronic background

    # 5. Construct input (.in) and expected X-ray output (.xr.out) filenames inside OUTPUT_DIR
    filename = os.path.join(OUTPUT_DIR, f"input_{element_name}_{safe_name}.in")
    xr_filename = os.path.join(OUTPUT_DIR, f"input_{element_name}_{safe_name}.xr.out")

    # 6. Delete stale output file if it exists to guarantee fresh simulation results
    if os.path.exists(xr_filename):
        os.remove(xr_filename)

    # 7. Write the transition command and physical parameters to the MUDIRAC input file
    with open(filename, "w") as file:
        file.write(f"xr_lines: {xr_lines}\n")
        for key, value in params.items():
            if isinstance(value, bool):
                val_str = "TRUE" if value else "FALSE"
            else:
                val_str = str(value)
            file.write(f"{key}: {val_str}\n")

    if verbose:
        print(f'Created "{filename}" for element: {element_name}, transitions: {xr_lines}')

    # 8. Execute the MUDIRAC binary and verify successful completion
    try:
        subprocess.run(["./mudirac", filename], capture_output=True, text=True, check=True)
        if verbose:
            print("-> Simulation ran successfully!")
        return filename
    except FileNotFoundError:
        print("-> Error: MUDIRAC executable './mudirac' not found in this folder.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"-> Error running simulation: {e}")
        if e.stdout:
            print(f"   MUDIRAC Output: {e.stdout.strip()}")
        if e.stderr:
            print(f"   MUDIRAC Error:  {e.stderr.strip()}")
        return None


def parse_mudirac_xr(input_filename, verbose=False):
    """
    Finds and parses the .xr.out file generated by MUDIRAC,
    extracting valid transition energies (eV) and rates (s^-1) into a dictionary.
    """
    # Safety check in case create_mudirac_input failed and returned None
    if not input_filename:
        return None

    # Replace the '.in' extension with '.xr.out'
    base_name = os.path.splitext(input_filename)[0]
    xr_filename = f"{base_name}.xr.out"

    # Verify that MUDIRAC actually created the output file
    if not os.path.exists(xr_filename):
        if verbose:
            print(f"-> Warning: Output file '{xr_filename}' not found.")
        return None

    results = {}

    if verbose:
        print(f"\n--- Physical Results from {xr_filename} ---")

    # Read and parse the output file line by line
    with open(xr_filename, "r") as file:
        for line in file:
            line = line.strip()

            # Skip empty lines and comment lines starting with '#'
            if not line or line.startswith("#"):
                continue

            # Split the line by whitespace into a list of tokens
            parts = line.split()

            # Ensure this is a valid data row (at least 3 columns) and skip the header row
            if len(parts) >= 3 and parts[0] != "Line":
                transition = parts[0]
                energy_ev = float(parts[1])
                rate_s = float(parts[2])

                # Keep only physically valid spontaneous emissions (positive energy and rate)
                if energy_ev > 0 and rate_s > 0:
                    results[transition] = {
                        "energy_eV": energy_ev,
                        "rate_s": rate_s
                    }

                    # Print detailed transition metrics only if verbose logging is requested
                    if verbose:
                        print(f"Transition: {transition}")
                        print(f" -> Energy: {energy_ev / 1000:.3f} keV")
                        print(f" -> Rate:   {rate_s:.3e} s^-1")

    return results


def plot_wavefunction(state_filename):
    """
    Reads a MUDIRAC radial state file (.out) and plots the relativistic Dirac 
    wavefunction components P(r) and Q(r) with an adaptive radial cutoff.
    """
    # Verify that the state file exists on disk
    if not os.path.exists(state_filename):
        print(f"-> Error: State file '{state_filename}' not found.")
        return None

    # Safely load the numerical grid and validate its 4-column structure
    try:
        data = np.loadtxt(state_filename, comments="#")
    except ValueError as e:
        print(f"-> Error: Failed to parse numerical data from '{state_filename}': {e}")
        return None

    if data.ndim != 2 or data.shape[1] < 4:
        print(f"-> Error: File '{state_filename}' does not contain a valid 4-column radial grid.")
        return None

    # Extract radial grid r [a.u.], major component P(r), and minor component Q(r)
    r = data[:, 0]
    p_major = data[:, 2]
    q_minor = data[:, 3]

    # Determine dynamic radial cutoff where amplitude drops below 0.5% of its global peak
    max_p = np.max(np.abs(p_major))
    if max_p == 0:
        print(f"-> Warning: Wavefunction in '{state_filename}' is identically zero.")
        return None

    significant_indices = np.where(np.abs(p_major) > 0.005 * max_p)[0]
    r_max = r[significant_indices[-1]] * 1.25

    # Slice the arrays to focus the plot on the physically active radial region
    mask = r <= r_max
    r_plot = r[mask]
    p_plot = p_major[mask]
    q_plot = q_minor[mask]

    # Plot major P(r) and minor Q(r) relativistic Dirac components
    plt.figure(figsize=(10, 6))
    plt.plot(r_plot, p_plot, label=r"Major Component $P(r)$", color="royalblue", linewidth=2.0)
    plt.plot(r_plot, q_plot, label=r"Minor Component $Q(r)$", color="crimson", linewidth=1.5)

    # Configure zero-axis reference line, scientific notation, labels, and grid
    plt.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.7)
    plt.title(f"Muonic Radial Dirac Wavefunction: {os.path.basename(state_filename)}", fontsize=14)
    plt.xlabel(r"Radius $r$ [a.u.]", fontsize=12)
    plt.ylabel(r"Wavefunction Amplitude [a.u.$^{-1/2}$]", fontsize=12)
    plt.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
    plt.legend(fontsize=12, loc="best")
    plt.grid(True, alpha=0.3, linestyle="--")

    # Save the figure at publication quality (300 DPI) and return the file path
    plot_filename = f"{os.path.splitext(state_filename)[0]}_plot.png"
    plt.savefig(plot_filename, dpi=300, bbox_inches="tight")
    plt.close()

    print(f"-> Wavefunction plot saved as: {plot_filename}")
    return plot_filename


def e1_allowed_line(line):
    """line = 'TARGET-SOURCE' in MUDIRAC codes (e.g. 'O8-R6'). True if the electric-dipole selection rules allow it
    (Delta l = +-1, |Delta j| <= 1; MUDIRAC paper, Sec. 2.3). An unknown line counts as allowed (never ignored)."""
    def lj(code):
        m = re.match(r"(\d+)([a-z])_(\d+)/2$", inverse_mudirac_dict[code])
        return l_symbols.index(m.group(2)), int(m.group(3)) / 2
    try:
        tgt, src = line.split("-")
        (l1, j1), (l2, j2) = lj(tgt), lj(src)
    except (ValueError, KeyError, AttributeError):
        return True
    return abs(l1 - l2) == 1 and abs(j1 - j2) <= 1


def skipped_allowed_lines(input_filename):
    """The dipole-allowed lines MUDIRAC dropped from a run ("Convergence of one state failed ... skipping"). MUDIRAC
    still writes the other lines, but a branching ratio needs the rates of ALL allowed decay channels of the level."""
    log_path = os.path.splitext(input_filename)[0] + ".log"
    if not os.path.exists(log_path):
        return []
    with open(log_path, errors="ignore") as fh:
        log = fh.read()
    names = re.findall(r"failed for line (\S+), skipping", log) + re.findall(r"Skipping line (\S+) because", log)
    return sorted({n for n in names if e1_allowed_line(n)})


def run_was_clean(input_filename):
    """True if the MUDIRAC log of this run shows no error and no state that failed to converge."""
    log_path = os.path.splitext(input_filename)[0] + ".log"
    if not os.path.exists(log_path):
        return False
    with open(log_path, errors="ignore") as fh:
        log = fh.read()
    return "Calculation completed" in log and "[Err]" not in log and "failed" not in log


def calculate_branching_ratios(source_level, element="C", print_table=True, **kwargs):
    """
    Calculates the normalized transition probabilities (Branching Ratios) 
    from a given source level to ALL possible lower levels in a single MUDIRAC run.
    """
    # 1. Check if this exact state and physical model configuration is already in memory cache
    cache_key = (element, source_level, tuple(sorted(kwargs.items())))
    if cache_key in live_cache:
        return live_cache[cache_key]

    # 2. Ground state (n=1) has no lower levels to decay to
    if get_n(source_level) == 1:
        return []

    if print_table:
        print(f"\n{'='*75}")
        print(f" Analyzing decay paths for level: {source_level} (Element: {element})")
        print(f"{'='*75}")

    # 3. Run MUDIRAC once for all lower shells using target="ALL_LOWER" (output: 2 also writes the radial wavefunctions
    #    of the states involved; they are kept for the wavefunction window). If MUDIRAC does not converge, the run is
    #    repeated with a smaller energy damping: a purely numerical solver setting, the physics stays exactly the same.
    #    Nothing else is ever substituted: if MUDIRAC gives no result, the result is empty and the caller must say so.
    res = None
    clean_but_empty = False       # MUDIRAC ran without any failure and found no downward dipole line (e.g. 2s in muonic H)
    for step in RETRY_STEPS:
        run_kwargs = dict(kwargs)
        run_kwargs.setdefault("output", 2)
        run_kwargs.update(step)
        input_filename = create_mudirac_input(
            level_name=source_level,
            target="ALL_LOWER",
            verbose=print_table,
            element=element,
            **run_kwargs
        )
        res = parse_mudirac_xr(input_filename, verbose=False) if input_filename else None
        if input_filename and not res and run_was_clean(input_filename):
            clean_but_empty = True
        if res and skipped_allowed_lines(input_filename):
            # an allowed decay channel is missing: the rates would be normalised over fewer channels and the branching
            # ratios would be wrong. Like the MUDIRAC paper (lines that did not succeed are left out), no complete result
            # exists for this level with these settings; the next (smaller) damping is tried, then it is "no result".
            res = None
        if res:
            harvest_wavefunctions(input_filename, element, kwargs)
        # 6. Clean up every temporary MUDIRAC file of this run (.in, .xr.out, .log, .err, state and matrix files)
        if input_filename:
            base = os.path.splitext(input_filename)[0]
            for f in glob.glob(glob.escape(base) + ".*"):
                try:
                    os.remove(f)
                except OSError:
                    pass
        if res:
            if step and print_table:
                print(f"-> converged with the solver setting {step}")
            break
        if clean_but_empty:
            break                 # nothing failed: more attempts cannot create a line that does not exist

    transitions = []
    total_rate = 0.0

    # 5. Extract valid transitions and translate MUDIRAC codes back to physical level names
    if res:
        for line_name, data in res.items():
            target_code = line_name.split("-")[0]
            target_name = inverse_mudirac_dict.get(target_code, target_code)
            rate = data["rate_s"]

            transitions.append({
                "Target Level": target_name,
                "Line": line_name,
                "Energy (keV)": data["energy_eV"] / 1000.0,
                "Rate (s^-1)": rate
            })
            total_rate += rate
    # 7. Calculate the normalized Branching Ratio (Probability in %) for each transition path
    for t in transitions:
        t["Probability (%)"] = (t["Rate (s^-1)"] / total_rate) * 100.0 if total_rate > 0 else 0.0

    # 8. Sort transitions from highest probability to lowest
    transitions.sort(key=lambda x: x["Probability (%)"], reverse=True)

    # 9. Print formatted summary table of all allowed transitions
    if print_table:
        print(f"\n{'='*75}")
        print(f"{'Target Level':<15} | {'Line':<8} | {'Energy (keV)':<14} | {'Rate (s^-1)':<12} | {'Probability':<12}")
        print(f"{'-'*75}")
        for row in transitions:
            print(f"{row['Target Level']:<15} | {row['Line']:<8} | {row['Energy (keV)']:<14.3f} | {row['Rate (s^-1)']:<12.3e} | {row['Probability (%)']:.2f}%")
        print(f"{'='*75}\n")

    # 10. Store in cache only if valid transitions were found
    if transitions:
        live_cache[cache_key] = transitions
        return transitions
    # no line: [] = MUDIRAC ran cleanly and the level has no downward dipole decay; None = MUDIRAC gave no (complete) result
    return [] if clean_but_empty else None


def run_monte_carlo_cascade(start_level="7i_13/2", element="C", num_muons=10000, **kwargs):
    """
    Simulates a full Monte Carlo cascade of N muons starting from start_level down to 1s_1/2,
    collects all emitted X-ray photon energies, and plots the resulting emission spectrum.
    """
    print(f"\n🚀 Running Monte Carlo Cascade: {num_muons:,} muons from {start_level} in {element}...")
    emitted_photons = []
    config_tuple = tuple(sorted(kwargs.items()))

    # 1. Simulate the cascade trajectory for each individual muon
    for i in range(num_muons):
        current_level = start_level
        if i == 0:
            print("\n🔍 First Muon Trajectory:")

        # 2. Step down shell-by-shell until reaching the 1s_1/2 ground state
        while current_level != "1s_1/2":
            # Print the branching ratio table only the first time a level is visited
            cache_key = (element, current_level, config_tuple)
            is_new_level = cache_key not in live_cache

            transitions = calculate_branching_ratios(
                current_level, element=element, print_table=is_new_level, **kwargs
            )

            # Abort immediately if the starting level itself failed to calculate
            if not transitions:
                if i == 0 and current_level == start_level:
                    print("-> Cascade aborted: Could not calculate transitions from start_level.")
                    return []
                break

            targets = [t["Target Level"] for t in transitions]
            probs = [t["Probability (%)"] for t in transitions]
            energies = [t["Energy (keV)"] for t in transitions]

            # 3. Randomly select the next level weighted by branching probabilities
            chosen_idx = random.choices(range(len(targets)), weights=probs, k=1)[0]
            
            if i == 0:
                print(f"   Step: {current_level:<10} -> {targets[chosen_idx]:<10} ({energies[chosen_idx]:.3f} keV)")

            emitted_photons.append(energies[chosen_idx])
            current_level = targets[chosen_idx]

    # 4. Verify that photons were emitted before attempting to plot
    if not emitted_photons:
        print("-> No photons were emitted during the simulation.")
        return []

    print(f"\n✅ Simulation complete! Total X-ray photons emitted: {len(emitted_photons):,}")

    # 5. Plot and save the resulting X-ray spectrum inside OUTPUT_DIR
    plt.figure(figsize=(10, 5))
    bins = np.linspace(0, max(emitted_photons) * 1.05, 400)
    plt.hist(emitted_photons, bins=bins, color="royalblue", edgecolor="navy")
    plt.title(f"Simulated Muonic X-Ray Spectrum for {element} (Start: {start_level}, N={num_muons:,})")
    plt.xlabel("Photon Energy [keV]")
    plt.ylabel("Counts (Intensity)")
    plt.yscale("log")
    plt.grid(True, alpha=0.3, ls="--")

    safe_start = start_level.replace("_", "-").replace("/", "_")
    out_img = os.path.join(OUTPUT_DIR, f"spectrum_{element}_{safe_start}.png")

    # Safely remove previous image if it exists, and handle Windows file locks on WSL
    try:
        if os.path.exists(out_img):
            os.remove(out_img)
        with open(out_img, "wb") as f:
            plt.savefig(f, format="png", dpi=300, bbox_inches="tight")
        print(f"📊 Spectrum plot saved as: {out_img}\n")
    except OSError:
        # Fallback if the image is currently open/locked in Windows Photos
        alt_img = os.path.join(OUTPUT_DIR, f"spectrum_{element}_{safe_start}_new.png")
        with open(alt_img, "wb") as f:
            plt.savefig(f, format="png", dpi=300, bbox_inches="tight")
        print(f"⚠️ '{out_img}' is open in Windows. Saved instead as: {alt_img}\n")
    finally:
        plt.close()
    
    return emitted_photons

# === Main Execution Block ===
if __name__ == "__main__":
    # Runs automatically with FERMI2, Uehling QED, [Fe] electron screening, and reduced mass
    photons = run_monte_carlo_cascade(
        start_level="7h_11/2",
        element="Fe",
        num_muons=10000
    )

    '''
    # Wavefunction plotting test block:
    in_file = create_mudirac_input(
        level_name="2p_3/2",
        target="1s_1/2",
        element="Cl",
        output=2,
        nuclear_model="FERMI2",
        uehling_correction=True
    )

    if in_file:
        base_name = os.path.splitext(in_file)[0]
        state_2p = f"{base_name}.{mudirac_dict['2p_3/2']}.out"
        state_1s = f"{base_name}.{mudirac_dict['1s_1/2']}.out"

        plot_wavefunction(state_2p)
        plot_wavefunction(state_1s)
    '''





    