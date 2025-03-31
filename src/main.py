import tkinter as tk
from tkinter import ttk, filedialog
from tkinter.messagebox import showerror
import zipfile
import os
import re
import time
import json
import shutil
import datetime
import subprocess
import tempfile
from FDP import compute_rsmt
import sys
# DEBUG: True  -> skip to main_screen (The window where we optimize RSMT), load test_cases.txt and fill signals_array with it.
#        False -> open start_screen (The window to choose design files), load the selected design and fill signals_array with it.
DEBUG = "-D" in sys.argv
def load_test_cases(file_path):
    try:
        with open(file_path, 'r') as file:
            content = file.read()
            test_cases = eval(content)  # בטוח אם הקובץ מקומי ונשלט
            return test_cases
    except FileNotFoundError:
        print(f"File {file_path} not found.")
        return {}
    except Exception as e:
        print(f"Error loading test cases: {e}")
        return {}
script_dir = os.path.dirname(os.path.abspath(__file__))
test_cases_path = os.path.join(script_dir, "..", "tests", "test_cases.txt")
test_cases = load_test_cases(test_cases_path)


# globals
open_windows = {}  # Dictionary to track open windows
main_screen = None  # Declare main_screen at the module level
signals_array = None  # Declare signals_array at the module level
components_array = None  # Declare components_array at the module level
save_optimization_var = None  # Declare save_optimization_var at the module level
optimization_folder_path = None
log_file_path = None
typcal_capacitance = 0.2  # [μF/μm]
typcal_resistance = 0.1  # [Ω/μm]

# global func
def setup_log_file(log_file):
    open(log_file, "w").close()  # Opens the file in write mode to clear its contents
def log_and_print(message):
    print(message)
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")
def build_signals_array(verilog_content, signal_dropdown):
    # List of reserved words that are not included in the signals array
    reserved_words = {"input", "output", "wire", "module", "endmodule"}
    # Regular expression to search for signal names
    signal_pattern = r"\b(?:input|output|wire)\b(?:\s+\w+)*\s+(\w+)(?:\s*,\s*(\w+))*"
    matches = re.findall(signal_pattern, verilog_content)
    # Storing signal names
    signals = {}
    for match in matches:
        # Collect all signal names that appear in the same definition
        for signal_name in match:
            if signal_name and signal_name not in reserved_words:  # Ignore empty values and reserved words
                signals[signal_name] = {"positions": []}
    # Search for occurrences of the signals in the file
    for signal in signals.keys():
        usage_pattern = fr"\b{signal}\b"
        matches = [(m.start(), m.end()) for m in re.finditer(usage_pattern, verilog_content)]
        positions_count = len(matches)
        # Subtract one occurrence for signals in the form n<number>
        if re.match(r"^n\d+$", signal):  # Detect signals that start with 'n' followed by a number
            positions_count = max(positions_count - 1, 0)  # Subtract one occurrence
        signals[signal]["positions"] = [(0, 0)] * positions_count  # Fill with tuples (0, 0)
    # Populate the dropdown
    signal_dropdown["values"] = list(signals.keys())
    if signals:
        signal_dropdown.current(0)  # Select the first item as default
    # Print the arrays
    log_and_print("Initialize signals array:")
    for signal, data in signals.items():
        log_and_print(f"{signal} ({len(data['positions'])} occurrences): {data['positions']}")
    # Print an empty line
    log_and_print("")
    return signals
def fill_pin_positions(def_content, signals):
    log_and_print("Updating pin positions within components:")
    inside_pins_macro = False  # Flag to identify when inside the PINS macro
    current_pin_name = None  # Current pin name being processed
    # Iterating over the lines of the file
    for line in def_content.splitlines():
        line = line.strip()  # Removing unnecessary spaces at the beginning and end of the line
        # Detecting the start of the PINS macro
        if line.startswith("PINS"):
            inside_pins_macro = True
            continue
        # Detecting the end of the PINS macro
        if inside_pins_macro and line.startswith("END PINS"):
            inside_pins_macro = False
            continue
        # If we are inside the PINS macro
        if inside_pins_macro:
            # Detecting the signal name
            pin_match = re.match(r"^-\s+(\w+)", line)
            if pin_match:
                current_pin_name = pin_match.group(1)  # Current pin name
                continue
            # Searching for position in lines containing "PLACED"
            if current_pin_name and "PLACED" in line:
                placed_match = re.search(r"PLACED\s+\(\s*(\d+)\s+(\d+)\s*\)", line)
                if placed_match:
                    x, y = map(int, placed_match.groups())  # Converting position values to integers
                    if current_pin_name in signals:
                        signals[current_pin_name]["positions"][0] = (x, y)  # Updating the position
                        log_and_print(f"Updated position for pin '{current_pin_name}': ({x}, {y})")  # Debug
                current_pin_name = None  # Resetting the current pin name after updating
    # Printing the updated array
    log_and_print("")
    log_and_print("Updated Signals array after pins readout:")
    for signal, data in signals.items():
        log_and_print(f"{signal} ({len(data['positions'])} occurrences): {data['positions']}")
    # Printing an empty line
    log_and_print("")
def build_components_array(def_content):
    components = {}  # Array for the components
    inside_components_macro = False  # Flag to identify when inside the COMPONENTS macro
    component_name = None  # Initialize before the loop
    # Iterating over the lines of the file
    for line in def_content.splitlines():
        line = line.strip()  # Removing unnecessary spaces
        # Detecting the start of the COMPONENTS macro
        if line.startswith("COMPONENTS"):
            inside_components_macro = True
            continue
        # Detecting the end of the COMPONENTS macro
        if inside_components_macro and line.startswith("END COMPONENTS"):
            inside_components_macro = False
            continue
        # If we are inside the COMPONENTS macro
        if inside_components_macro:
            # Detecting the component name and logic gate
            component_match = re.match(r"^-\s+(\w+)\s+(\w+)", line)
            if component_match:
                component_name = component_match.group(1)  # Component name
                logic_gate = component_match.group(2)  # Logic gate
                components[component_name] = [logic_gate, (0, 0), (0, 0), (0, 0), (0, 0)]  # Create the record
            # Detecting the component's location after the word "PLACED"
            placed_match = re.search(r"PLACED\s+\(\s*(\d+)\s+(\d+)\s*\)", line)
            if placed_match and component_name in components:
                x, y = map(int, placed_match.groups())
                components[component_name][1] = (x, y)  # Update the component's location on the chip
    # Printing the updated array
    log_and_print("Initialize components array with the component location on the chip:")
    for component, data in components.items():
        log_and_print(f"{component}: logic gate: {data[0]}. Component location: {data[1]}. "
                      f"Input A location: {data[2]}. Input B location: {data[3]}. Output Y location: {data[4]}.")
    log_and_print("")
    return components
def fill_components_array(lef_content, components):
    inside_macro = False  # Flag to identify when inside a logic gate macro
    current_macro_name = None  # Current macro name (logic gate)
    current_pin_name = None  # Current PIN name
    # Iterating over the lines of the LEF file
    for line in lef_content.splitlines():
        line = line.strip()  # Removing unnecessary spaces
        # Detecting the start of a macro
        macro_match = re.match(r"^MACRO\s+(\w+)", line)
        if macro_match:
            current_macro_name = macro_match.group(1)
            inside_macro = True
            continue
        # Detecting the end of a macro
        if inside_macro and line.startswith("END"):
            if f"END {current_macro_name}" in line:
                inside_macro = False
                current_macro_name = None
                current_pin_name = None
            continue
        # If we are inside the current logic gate macro
        if inside_macro:
            # Detecting a PIN
            pin_match = re.match(r"^PIN\s+(\w+)", line)
            if pin_match:
                current_pin_name = pin_match.group(1)
                continue
            # Searching for RECT and the PIN's position
            rect_match = re.search(r"RECT\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", line)
            if rect_match and current_macro_name:
                x1, y1, x2, y2 = map(float, rect_match.groups())
                x_center = (x1 + x2) / 2
                y_center = (y1 + y2) / 2
                # Calculating the PIN's position
                for component_name, data in components.items():
                    if data[0] == current_macro_name:  # Check if the logic gate matches
                        component_location = data[1]
                        pin_location = (
                            component_location[0] + x_center,
                            component_location[1] + y_center,
                        )
                        # Updating the appropriate location
                        if current_pin_name == "A":
                            components[component_name][2] = pin_location
                        elif current_pin_name == "B":
                            components[component_name][3] = pin_location
                        elif current_pin_name == "Y":
                            components[component_name][4] = pin_location
    # Printing the updated array
    log_and_print("The complete components array:")
    for component, data in components.items():
        log_and_print(f"{component}: logic gate: {data[0]}. Component location: {data[1]}. "
                      f"Input A location: {data[2]}. Input B location: {data[3]}. Output Y location: {data[4]}.")
    log_and_print("")
    return components
def complete_signals_array(verilog_content, signals, components):
    # Searching for the start of operations lines after wire declarations
    wire_end_pattern = re.compile(r"^\s*wire\b.*;")
    wire_section_found = False
    # Iterating over the lines
    for line in verilog_content.splitlines():
        line = line.strip()
        # Detecting the end of wire declarations
        if not wire_section_found:
            if wire_end_pattern.search(line):
                wire_section_found = True
            continue
        # Detecting lines that describe components
        component_match = re.match(r"^(\w+)\s+(\w+)\s*\(([^)]+)\);", line)
        if component_match:
            # gate_type = component_match.group(1)  # Gate type
            component_name = component_match.group(2)  # Component name
            signals_inside = component_match.group(3).split(",")  # List of signals
            signals_inside = [sig.strip() for sig in signals_inside]  # Stripping whitespace
            # Ensuring the component exists in the components array
            if component_name in components:
                # Mapping locations for the current component
                component_data = components[component_name]
                output_location = component_data[4]  # Y location
                input_a_location = component_data[2]  # A location
                input_b_location = component_data[3]  # B location
                # Updating the signals array
                for i, signal in enumerate(signals_inside):
                    if signal in signals:
                        # Selecting the location to fill
                        if i == 0:  # Output
                            location = output_location
                        elif i == 1:  # Input A
                            location = input_a_location
                        elif i == 2:  # Input B
                            location = input_b_location
                        else:
                            continue
                        # Filling the first empty slot
                        for j in range(len(signals[signal]["positions"])):
                            if signals[signal]["positions"][j] == (0, 0):
                                signals[signal]["positions"][j] = location
                                break
    # Printing the updated array
    log_and_print("The complete signals array:")
    for signal, data in signals.items():
        log_and_print(f"{signal} ({len(data['positions'])} occurrences): {data['positions']}")
    log_and_print("")
    return signals
def draw_axis_with_grid(canvas, width, height, grid_spacing):
    # Y-axis: עולה מלמטה למעלה
    canvas.create_line(0, height, 0, 0, fill="black", width=2)  # Y-axis
    canvas.create_line(0, height, width, height, fill="black", width=2)  # X-axis
    num_x_lines = int(width / grid_spacing)
    num_y_lines = int(height / grid_spacing)
    # Horizontal GRID lines (מימין לשמאל, מהתחתית כלפי מעלה)
    for i in range(num_y_lines + 1):
        y = height - i * grid_spacing  # הפוך את כיוון Y
        canvas.create_line(0, y, width, y, fill="#f0f0f0")
    # Vertical GRID lines (רגיל)
    for i in range(num_x_lines + 1):
        x = i * grid_spacing
        canvas.create_line(x, 0, x, height, fill="#f0f0f0")
def draw_signal_points(canvas, points):
    canvas.delete("signal_point")
    canvas.delete("steiner_point")
    canvas.delete("m1_edge")
    canvas.delete("m2_edge")
    canvas_height = int(canvas["height"])  # קריאה לגובה הקנבס
    for x, y in points:
        y_transformed = canvas_height - y  # הפוך את Y
        canvas.create_oval(
            x - 5, y_transformed - 5, x + 5, y_transformed + 5,
            fill="blue", outline="blue", tags="signal_point"
        )
def save_optimization_data(signal_name, signal_points, steiner_points, M1, M2, runtime):
    global optimization_folder_path
    # Create signal folder (overwrite if exists)
    signal_folder = os.path.join(optimization_folder_path, signal_name)
    if os.path.exists(signal_folder):
        shutil.rmtree(signal_folder)
    os.makedirs(signal_folder)
    # JSON Data Structure
    json_data = {
        "Design_Name": os.path.basename(optimization_folder_path),
        "Signal_Name": signal_name,
        "Optimization_Runtime": f"{runtime:.4f} seconds",
        "Points": {
            "Design_Points": {
                "Number": len(signal_points),
                "Desgin points coordinates": {
                    f"P{i + 1}": list(coord) for i, coord in enumerate(signal_points)
                }
            },
            "Steiner_Points": {
                "Number": len(steiner_points),
                "Steiner points coordinates": {
                    f"S{i + 1}": list(coord) for i, coord in enumerate(steiner_points)
                }
            }
        },
        "Wires": {}
    }
    # Helper to calculate wire data
    def process_wires(edges, metal_name):
        total_len = total_cap = total_res = 0
        wires_info = {}
        for idx, ((x1, y1), (x2, y2)) in enumerate(edges, 1):
            length = abs(x1 - x2) + abs(y1 - y2)
            cap = length * 0.2
            res = length * 0.1
            total_len += length
            total_cap += cap
            total_res += res
            wires_info[f"wire_{idx}"] = {
                "Start": [x1, y1],
                "End": [x2, y2],
                "Length": length,
                "Capacitance": round(cap, 3),
                "Resistance": round(res, 3)
            }
        return total_len, total_cap, total_res, wires_info
    m1_len, m1_cap, m1_res, m1_info = process_wires(M1, "M1")
    m2_len, m2_cap, m2_res, m2_info = process_wires(M2, "M2")
    json_data["Wires"] = {
        "Wires_total_length_(RSMT)": round(m1_len + m2_len, 2),
        "Wires_total_capacitance": round(m1_cap + m2_cap, 2),
        "Wires_total_resistance": round(m1_res + m2_res, 2),
        "M1_Wires": {
            "Number": len(M1),
            "M1_wires_total_length": m1_len,
            "M1_wires_total_capacitance": m1_cap,
            "M1_wires_total_resistance": m1_res,
            "M1_wires_coordinates": m1_info
        },
        "M2_Wires": {
            "Number": len(M2),
            "M2_wires_total_length": m2_len,
            "M2_wires_total_capacitance": m2_cap,
            "M2_wires_total_resistance": m2_res,
            "M2_wires_coordinates": m2_info
        }
    }
    # Save JSON file
    json_path = os.path.join(signal_folder, f"{signal_name}_optimization_data.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, indent=4)
    # Screenshot of the window using PIL.ImageGrab
    screenshot_path = os.path.join(signal_folder, f"{signal_name}_optimization_route.png")
    main_screen.update_idletasks()
    main_screen.update_idletasks()
    time.sleep(0.2)  # השהייה של 100ms
    x = main_screen.winfo_rootx()
    y = main_screen.winfo_rooty()
    w = main_screen.winfo_width()
    h = main_screen.winfo_height()
    import mss
    import mss.tools
    try:
        with mss.mss() as sct:
            monitor = {"top": y, "left": x, "width": w, "height": h}
            img = sct.grab(monitor)
            mss.tools.to_png(img.rgb, img.size, output=screenshot_path)
    except Exception as e:
        print(f"Screenshot failed: {e}")
def FullTree(terminals):
    labels = {tuple(pt): f"P{i + 1}" for i, pt in enumerate(terminals)}
    n = len(terminals)
    if n < 2:
        return 0, []
    def connect(a, b, label_map, edges, s_counter):
        """Connect point a to b rectilinearly. Insert mid-point if needed."""
        a = (int(a[0]), int(a[1]))  # עיגול
        b = (int(b[0]), int(b[1]))  # עיגול
        if a == b:
            return 0, s_counter  # No connection needed
        # Assign labels if missing
        for pt in (a, b):
            if pt not in label_map:
                label_map[pt] = f"S{s_counter}"
                s_counter += 1
        if a[0] == b[0] or a[1] == b[1]:
            # Same row or column
            edges.append(f"{label_map[a]}({a[0]},{a[1]}) connects to {label_map[b]}({b[0]},{b[1]})")
            return abs(a[0] - b[0]) + abs(a[1] - b[1]), s_counter
        else:
            # Need mid-point
            mid = (int(a[0]), int(b[1]))  # עיגול של mid
            if mid not in label_map:
                label_map[mid] = f"S{s_counter}"
                s_counter += 1
            edges.append(f"{label_map[a]}({a[0]},{a[1]}) connects to {label_map[mid]}({mid[0]},{mid[1]})")
            edges.append(f"{label_map[mid]}({mid[0]},{mid[1]}) connects to {label_map[b]}({b[0]},{b[1]})")
            dist = abs(a[0] - mid[0]) + abs(a[1] - mid[1]) + abs(mid[0] - b[0]) + abs(mid[1] - b[1])
            return dist, s_counter
    if n == 2:
        p1, p2 = terminals[0], terminals[1]
        edges = []
        dist, _ = connect(p1, p2, labels.copy(), edges, 1)
        return dist, edges
    if n == 3:
        sorted_pts = sorted(terminals, key=lambda p: (p[0], p[1]))
        p1, p2, p3 = sorted_pts
        # Solution 1: median
        xs = [p[0] for p in sorted_pts]
        ys = [p[1] for p in sorted_pts]
        median_x = sorted(xs)[1]
        median_y = sorted(ys)[1]
        s_median = (median_x, median_y)
        label_median = labels.copy()
        label_median[s_median] = "S1"
        edges1 = []
        len1 = 0
        s_counter = 2
        for pt in sorted_pts:
            if pt == s_median:
                continue
            d, s_counter = connect(pt, s_median, label_median, edges1, s_counter)
            len1 += d
        # Solution 2: pairwise
        edges2 = []
        s_counter = 1
        label_pair = labels.copy()
        s1 = (p2[0], p1[1])
        d1, s_counter = connect(p1, s1, label_pair, edges2, s_counter)
        d2, s_counter = connect(s1, p2, label_pair, edges2, s_counter)
        s2 = (p3[0], p2[1])
        d3, s_counter = connect(p2, s2, label_pair, edges2, s_counter)
        d4, s_counter = connect(s2, p3, label_pair, edges2, s_counter)
        len2 = d1 + d2 + d3 + d4
        if len1 < len2:
            return len1, edges1
        else:
            return len2, edges2
    # n >= 4: pairwise solution
    sorted_pts = sorted(terminals, key=lambda p: (p[0], p[1]))
    pair_edges = []
    pair_length = 0
    s_counter = 1
    label_pair = labels.copy()
    for i in range(len(sorted_pts) - 1):
        p1 = sorted_pts[i]
        p2 = sorted_pts[i + 1]
        if p1[0] != p2[0] and p1[1] != p2[1]:
            s = (p2[0], p1[1])
            d1, s_counter = connect(p1, s, label_pair, pair_edges, s_counter)
            d2, s_counter = connect(s, p2, label_pair, pair_edges, s_counter)
            pair_length += d1 + d2
        else:
            d, s_counter = connect(p1, p2, label_pair, pair_edges, s_counter)
            pair_length += d
    # Method 2: Hwang’s algorithm
    xs = [x for x, y in terminals]
    ys = [y for x, y in terminals]
    idx_minx = xs.index(min(xs))
    idx_maxx = xs.index(max(xs))
    idx_miny = ys.index(min(ys))
    idx_maxy = ys.index(max(ys))
    best_length = float('inf')
    best_edges = []
    def evaluate_topology(r_idx, t_idx, orientation):
        if r_idx == t_idx:
            return None
        r = terminals[r_idx]
        t = terminals[t_idx]
        edges = []
        label_top = labels.copy()
        s_counter = 1
        total_length = 0
        if orientation == 'H':
            main_y = r[1]
            chain_xs = sorted(set([r[0], t[0]] + [p[0] for i, p in enumerate(terminals) if i not in (r_idx, t_idx)]))
            chain_pts = [(x, main_y) for x in chain_xs]
            for i in range(len(chain_pts) - 1):
                d, s_counter = connect(chain_pts[i], chain_pts[i + 1], label_top, edges, s_counter)
                total_length += d
            d, s_counter = connect(t, (t[0], main_y), label_top, edges, s_counter)
            total_length += d
            for i, p in enumerate(terminals):
                if i in (r_idx, t_idx):
                    continue
                d, s_counter = connect(p, (p[0], main_y), label_top, edges, s_counter)
                total_length += d
        else:
            main_x = r[0]
            chain_ys = sorted(set([r[1], t[1]] + [p[1] for i, p in enumerate(terminals) if i not in (r_idx, t_idx)]))
            chain_pts = [(main_x, y) for y in chain_ys]
            for i in range(len(chain_pts) - 1):
                d, s_counter = connect(chain_pts[i], chain_pts[i + 1], label_top, edges, s_counter)
                total_length += d
            d, s_counter = connect(t, (main_x, t[1]), label_top, edges, s_counter)
            total_length += d
            for i, p in enumerate(terminals):
                if i in (r_idx, t_idx):
                    continue
                d, s_counter = connect(p, (main_x, p[1]), label_top, edges, s_counter)
                total_length += d
        return total_length, edges
    extreme_indices = {'minx': idx_minx, 'maxx': idx_maxx, 'miny': idx_miny, 'maxy': idx_maxy}
    for r_key in ['minx', 'maxx']:
        r_idx = extreme_indices[r_key]
        t_options = (['maxx'] if r_key == 'minx' else ['minx']) + ['miny', 'maxy']
        for t_key in t_options:
            t_idx = extreme_indices[t_key]
            result = evaluate_topology(r_idx, t_idx, orientation='H')
            if result and result[0] < best_length:
                best_length, best_edges = result
    for r_key in ['miny', 'maxy']:
        r_idx = extreme_indices[r_key]
        t_options = (['maxy'] if r_key == 'miny' else ['miny']) + ['minx', 'maxx']
        for t_key in t_options:
            t_idx = extreme_indices[t_key]
            result = evaluate_topology(r_idx, t_idx, orientation='V')
            if result and result[0] < best_length:
                best_length, best_edges = result
    if pair_length <= best_length:
        return pair_length, pair_edges
    else:
        return best_length, best_edges
def optimize():
    """Function triggered by the 'Optimize' button."""
    global signals_array, save_optimization_var, signal_var
    global steiner_points_label, all_points_label, capacitance_label, resistance_label, RSMT_length_label
    global typcal_capacitance, typcal_resistance, optimization_folder_path
    start_time = time.perf_counter()
    # Retrieve the selected signal
    selected_signal = signal_var.get()
    if selected_signal in signals_array:
        signal_points = signals_array[selected_signal]["positions"]
        log_and_print(f"starting optimization for signal: {selected_signal}")
        log_and_print("")
        # מחשוב RSMT בעזרת GeoSteiner
        length, steiner_points, edges = compute_rsmt(signal_points)
        print(edges)
        edges = split_non_rectilinear_edges(edges) # For the purpose of counting segments 
        log_and_print(f"Total RSMT length: {length:.3f} [μM]")
        log_and_print("")
        log_and_print("Wire details:")
        # חישוב והדפסת פרטי כל חוט
        for (x1, y1), (x2, y2) in edges:
            wire_length = abs(x1 - x2) + abs(y1 - y2)
            capacitance = wire_length * typcal_capacitance
            resistance = wire_length * typcal_resistance
            log_and_print(
                f"P({int(x1)},{int(y1)}) connects to P({int(x2)},{int(y2)}): "
                f"length={wire_length:.3f} [μM], capacitance={capacitance:.3f} [μF], resistance={resistance:.3f} [μΩ]"
            )
        log_and_print("")
        # בניית תוצאה לציור
        result_dict = {
            "connections": edges,
            "steiner_points": steiner_points
        }
        # ציור הקווים והסטיינר בקנבס
        M1, M2 = draw_FDP_result(result_dict)
        # עדכון תוויות נתונים
        steiner_points_label.config(text=f"Number of steiner points: {len(steiner_points)}")
        RSMT_length_label.config(text=f"RSMT Length: {length:.3f} [μM]")
        total_points = len(steiner_points) + len(signal_points)
        all_points_label.config(text=f"Number of all points: {total_points}")
        end_time = time.perf_counter()
        elapsed_time = end_time - start_time
        runtime_label.config(text=f"Optimization Runtime: {elapsed_time:.4f} [s]")
        log_and_print(f"Optimization Runtime: {elapsed_time:.4f} seconds")
        log_and_print("")
        log_and_print(f"finished optimization for signal: {selected_signal}")
        log_and_print("")
        # שמירת תוצאה אם תיבת הסימון פעילה
        if save_optimization_var.get():
            log_and_print(f"saving optimization files for {selected_signal}")
            log_and_print("")
            save_optimization_data(selected_signal, signal_points, steiner_points, M1, M2, elapsed_time)
def draw_FDP_result(result):
    global drawing_canvas
    M1, M2 = edges_classification(result)
    canvas_height = int(drawing_canvas["height"])
    # חישובי נתונים – ללא שינוי (לא צריך להפוך Y כאן)
    m1_total_length = m1_total_cap = m1_total_res = 0.0
    for (x1, y1), (x2, y2) in M1:
        length = abs(x1 - x2) + abs(y1 - y2)
        m1_total_length += length
        m1_total_cap += length * 0.2
        m1_total_res += length * 0.1
    m2_total_length = m2_total_cap = m2_total_res = 0.0
    for (x1, y1), (x2, y2) in M2:
        length = abs(x1 - x2) + abs(y1 - y2)
        m2_total_length += length
        m2_total_cap += length * 0.2
        m2_total_res += length * 0.1
    capacitance_label.config(text=f"Capacitance of metals: {m1_total_cap + m2_total_cap:.3f} [μF]")
    resistance_label.config(text=f"Resistance of metals: {m1_total_res + m2_total_res:.3f} [μΩ]")
    log_and_print(
        f"Total M1 length: {m1_total_length:.3f}μm, capacitance: {m1_total_cap:.3f}μF, resistance: {m1_total_res:.3f}Ω")
    log_and_print(
        f"Total M2 length: {m2_total_length:.3f}μm, capacitance: {m2_total_cap:.3f}μF, resistance: {m2_total_res:.3f}Ω")
    log_and_print("M1 Wires (Horizontal):")
    for (x1, y1), (x2, y2) in M1:
        length = abs(x1 - x2) + abs(y1 - y2)
        cap = length * 0.2
        res = length * 0.1
        log_and_print(
            f"M1 | ({x1},{y1}) to ({x2},{y2}): length={length:.3f} [μM], capacitance={cap:.3f} [μF], resistance={res:.3f} [μΩ]")
    log_and_print("M2 Wires (Vertical):")
    for (x1, y1), (x2, y2) in M2:
        length = abs(x1 - x2) + abs(y1 - y2)
        cap = length * 0.2
        res = length * 0.1
        log_and_print(
            f"M2 | ({x1},{y1}) to ({x2},{y2}): length={length:.3f} [μM], capacitance={cap:.3f} [μF], resistance={res:.3f} [μΩ]")
    log_and_print("")
    # ציור נקודות סטיינר (אדומות)
    for x, y in result["steiner_points"]:
        y_transformed = canvas_height - y  # היפוך Y
        drawing_canvas.create_oval(
            int(x) - 5, y_transformed - 5, int(x) + 5, y_transformed + 5,
            fill="red", outline="red", tags="steiner_point"
        )
    # ציור קווי M1 (אופקיים – סגול)
    for (x1, y1), (x2, y2) in M1:
        y1_t = canvas_height - y1
        y2_t = canvas_height - y2
        drawing_canvas.create_line(x1, y1_t, x2, y2_t, fill="purple", width=3, tags="m1_edge")
    # ציור קווי M2 (אנכיים – כתום)
    for (x1, y1), (x2, y2) in M2:
        y1_t = canvas_height - y1
        y2_t = canvas_height - y2
        drawing_canvas.create_line(x1, y1_t, x2, y2_t, fill="orange", width=3, tags="m2_edge")
    return M1, M2
def edges_classification(result):
    M1 = []  # Horizontal edges
    M2 = []  # Vertical edges
    edges = result["connections"]
    for edge in edges:
        p1, p2 = edge
        if p1[1] == p2[1]:  # Same y-coordinate -> Horizontal
            M1.append(edge)
        elif p1[0] == p2[0]:  # Same x-coordinate -> Vertical
            M2.append(edge)
    return M1, M2
def split_non_rectilinear_edges(edges):
    """Split edges that are not axis-aligned into rectilinear segments."""
    rectilinear_edges = []
    for (x1, y1), (x2, y2) in edges:
        if x1 == x2 or y1 == y2:
            # חוקי – נשמר כמו שהוא
            rectilinear_edges.append(((x1, y1), (x2, y2)))
        else:
            # אלכסוני – נפרק ל־2 קווים דרך נקודת אמצע
            mid = (x2, y1)
            rectilinear_edges.append(((x1, y1), mid))
            rectilinear_edges.append((mid, (x2, y2)))
    return rectilinear_edges
def view_signals_data():
    global signals_array, open_windows
    # Check if the "Signals Data" window is already open
    if "Signals Data" in open_windows and open_windows["Signals Data"].winfo_exists():
        open_windows["Signals Data"].lift()  # Bring the existing window to the front
        return
    # Create a new window for displaying signal data
    signals_window = tk.Toplevel(main_screen)
    signals_window.title("Signals Data")
    signals_window.geometry("600x400")
    # Add a title label to the window
    tk.Label(signals_window, text="Signals Data", font=("Arial", 16, "bold")).pack(pady=10)
    # Create a text area to display the signal data
    text_area = tk.Text(signals_window, wrap=tk.WORD, font=("Courier", 10))
    text_area.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
    # Populate the text area with signal data
    for signal, data in signals_array.items():
        text_area.insert(tk.END, f"{signal} ({len(data['positions'])} occurrences): {data['positions']}\n")
    # Set the text area to be read-only
    text_area.config(state=tk.DISABLED)
    # Add the window to open_windows
    open_windows["Signals Data"] = signals_window
    # Handle window close to remove from open_windows
    def on_close():
        del open_windows["Signals Data"]
        signals_window.destroy()
    signals_window.protocol("WM_DELETE_WINDOW", on_close)
def view_components_data():
    global components_array, open_windows
    # Check if the "Components Data" window is already open
    if "Components Data" in open_windows and open_windows["Components Data"].winfo_exists():
        open_windows["Components Data"].lift()  # Bring the existing window to the front
        return
    # Create a new window for displaying component data
    components_window = tk.Toplevel(main_screen)
    components_window.title("Components Data")
    components_window.geometry("800x400")
    # Add a title label to the window
    tk.Label(components_window, text="Components Data", font=("Arial", 16, "bold")).pack(pady=10)
    # Create a text area to display the component data
    text_area = tk.Text(components_window, wrap=tk.WORD, font=("Courier", 10))
    text_area.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
    # Populate the text area with component data
    for component, data in components_array.items():
        text_area.insert(
            tk.END,
            f"{component}: logic gate: {data[0]}. Component location: {data[1]}. "
            f"Input A location: {data[2]}. Input B location: {data[3]}. Output Y location: {data[4]}.\n"
        )
    # Set the text area to be read-only
    text_area.config(state=tk.DISABLED)
    # Add the window to open_windows
    open_windows["Components Data"] = components_window
    # Handle window close to remove from open_windows
    def on_close():
        del open_windows["Components Data"]
        components_window.destroy()
    components_window.protocol("WM_DELETE_WINDOW", on_close)
# start_screen
def open_start_screen():
    def validate_zip_file(file_path):
        required_files = {".v", ".def", ".lef"}
        try:
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                extensions = {os.path.splitext(file)[1] for file in file_list}
                if required_files.issubset(extensions) and len(file_list) == 3:
                    return True
                else:
                    return False
        except zipfile.BadZipFile:
            return False
    def select_project_zip():
        file_path = filedialog.askopenfilename(filetypes=[("ZIP files", "*.zip")])
        if file_path:
            if validate_zip_file(file_path):
                start_screen.destroy()  # Closing the splash screen
                open_main_screen(file_path)  # Opening the main work screen
            else:
                showerror(
                    "Invalid ZIP File",
                    "Missing some or all required files. The required files are: example.v, example.def, example.lef"
                )
    # Main window for the splash screen
    start_screen = tk.Tk()
    start_screen.title("Routing Optimization Tool")
    window_width = 600
    window_height = 400
    screen_width = start_screen.winfo_screenwidth()
    screen_height = start_screen.winfo_screenheight()
    position_x = (screen_width // 2) - (window_width // 2)
    position_y = (screen_height // 2) - (window_height // 2)
    start_screen.geometry(f"{window_width}x{window_height}+{position_x}+{position_y}")
    title = tk.Label(start_screen, text="Routing Optimization Tool", font=("Arial", 20, "bold"))
    title.pack(pady=5)
    subtitle = tk.Label(
        start_screen,
        text=(
            "A Faster Dynamic Programming Algorithm for\n"
            "Exact Rectilinear Steiner Minimal Trees\n"
            "to Optimize Routing in VLSI Chip Design"
        ),
        font=("Arial", 12),
        justify="center",
        wraplength=500
    )
    subtitle.pack(pady=5)
    # Frame for the label and button
    frame = tk.Frame(start_screen)
    frame.pack(pady=5)
    # Label and button for selecting a ZIP file
    instruction = tk.Label(frame, text="Choose project zip file:", font=("Arial", 14))
    instruction.pack(side=tk.LEFT, padx=5)
    zip_file_btn = tk.Button(frame, text="Select ZIP File", command=select_project_zip)
    zip_file_btn.pack(side=tk.LEFT)
    # Adding a drawing between ZIP selection and developer credits
    canvas_width = 500
    canvas_height = 150
    canvas = tk.Canvas(start_screen, width=canvas_width, height=canvas_height, bg="white", highlightthickness=0)
    canvas.pack(pady=10)
    # חישוב מרכז הציור
    text_width = 4 * 40 + 3 * 120  # 4 אותיות, כל אחת רוחב 40, מרווח 120 בין אותיות
    start_x = (canvas_width - text_width) // 2  # התחלה אופקית - באמצע
    start_y = (canvas_height - 80) // 2  # גובה ציור 80, התחלה אנכית באמצע
    # Function to draw square letters with points and lines
    def draw_square_text(canvas, text, start_x, start_y, spacing, point_radius):
        letter_points = {
            'V': [(0, 0), (0, 80), (40, 80), (40, 0)],  # "V" without the top line, scaled
            'L': [(0, 0), (0, 80), (40, 80)],  # Coordinates for "L", scaled
            'S': [(40, 0), (0, 0), (0, 40), (40, 40), (40, 80), (0, 80)],  # Fixed "S", scaled
            'I': [(20, 0), (20, 80)]  # Coordinates for "I", scaled
        }
        current_x = start_x
        for char in text:
            if char in letter_points:
                points = letter_points[char]
                absolute_points = [(current_x + x, start_y + y) for x, y in points]
                # Draw lines between points
                for i in range(len(absolute_points) - 1):
                    x1, y1 = absolute_points[i]
                    x2, y2 = absolute_points[i + 1]
                    canvas.create_line(x1, y1, x2, y2, fill="black", width=2)
                # Draw points
                for x, y in absolute_points:
                    canvas.create_oval(
                        x - point_radius, y - point_radius,
                        x + point_radius, y + point_radius,
                        fill="blue", outline="blue"
                    )
                current_x += spacing
    # Draw "VLSI" on the canvas
    # draw_square_text(canvas, "VLSI", start_x=50, start_y=50, spacing=120, point_radius=5)
    draw_square_text(canvas, "VLSI", start_x=start_x + 75, start_y=start_y, spacing=120, point_radius=5)
    # Developer credits label
    developers_label = tk.Label(
        start_screen,
        text="This tool was developed by:\nEliraz Kadosh & Eliram Amrusi",
        font=("Arial", 10),
        justify="center"
    )
    developers_label.pack(pady=(5, 15))  # שומר רווח למטה אבל מעט מעלה את הטקסט
    start_screen.mainloop()
def choose_another_design():
    global log_file_path
    # ניקוי המסך ב-console
    os.system('cls' if os.name == 'nt' else 'clear')
    # סיום כתיבה לקובץ הלוג הנוכחי
    log_and_print("=== End of log for current design ===")
    log_and_print("")
    # סגירת המסך הראשי
    main_screen.destroy()
    # פתיחת מסך מחדש (או קובץ מוגדר מראש)
    if DEBUG:
        predefined_zip_path = os.path.join(script_dir, "..", "Input_Files", "16bit_shift_register_clk_not_in_line", "16bit_shift_register.zip")
        open_main_screen(predefined_zip_path)  # מסך חדש עם לוג חדש
    else:
        open_start_screen()  # מצב דיבאג - חזור למסך פתיחה
        



# main_screen
def open_main_screen(zip_file_path):
    global main_screen, signals_array, components_array, save_optimization_var, signal_var
    global drawing_canvas, log_file_path, optimization_folder_path  # Declare all global variables at the start
    global steiner_points_label, all_points_label, capacitance_label, resistance_label, RSMT_length_label, runtime_label  # Add these globals here
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Determine script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Get design name
    design_name_raw = os.path.splitext(os.path.basename(zip_file_path))[0]
    design_name = re.sub(r'[\u200f\u200e\u202a-\u202e]', '', design_name_raw)
    # Create folder: <design_name>_<date>_<time>
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = f"{design_name}_{timestamp}"
    # Step 1: הגדרת התיקייה של Output_Files
    output_dir = os.path.join(script_dir, "..", "Output_Files")
    os.makedirs(output_dir, exist_ok=True)



    optimization_folder_path = os.path.join(output_dir, folder_name)
    os.makedirs(optimization_folder_path, exist_ok=True)
    # Set log file path
    log_file_path = os.path.join(optimization_folder_path, "log.txt")
    # Extracting file names from the ZIP
    def extract_file_list(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            return zip_ref.namelist()
    # Displaying the content of a file in a new window
    def open_file_content(file_name):
        global open_windows
        if file_name in open_windows:
            # Bring the existing window to the front
            open_windows[file_name].lift()
            return
        try:
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                file_content = zip_ref.read(file_name).decode('utf-8')  # Read file content
            # Create a new window to display content
            content_window = tk.Toplevel(main_screen)
            content_window.title(f"File: {file_name}")
            content_window.geometry("800x600")
            # Add file content to the window
            tk.Label(content_window, text=file_name, font=("Arial", 14, "bold")).pack(pady=5)
            text_area = tk.Text(content_window, wrap=tk.WORD, font=("Courier", 10))
            text_area.insert(tk.END, file_content)
            text_area.config(state=tk.DISABLED)  # Make text read-only
            text_area.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)
            # Add to open_windows
            open_windows[file_name] = content_window
            # Handle window close
            def on_close():
                del open_windows[file_name]
                content_window.destroy()
            content_window.protocol("WM_DELETE_WINDOW", on_close)
        except Exception as e:
            showerror("Error", f"Unable to open the file: {e}")
    def extract_verilog_file(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(".v"):
                    return zip_ref.read(file_name).decode("utf-8")
        return None
    def extract_def_file(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(".def"):
                    return zip_ref.read(file_name).decode("utf-8")
        return None
    def extract_lef_file(zip_path):
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_name in zip_ref.namelist():
                if file_name.endswith(".lef"):
                    return zip_ref.read(file_name).decode("utf-8")
        return None
    # Overwriting the file at the start of the run
    setup_log_file(log_file_path)
    # positions
    p1x = 480
    p1y = 0
    p2x = 530
    p2y = 55
    p3x = 250
    p3y = 55
    p4x = 50
    p4y = 50
    p5x = 50
    p5y = 120
    p6x = 900
    p6y = 20
    p7x = 140
    p7y = 90
    p8x = 100
    p8y = 635
    p9x = 300
    p9y = 660
    p10x = 650
    p10y = 635
    p11x = 650
    p11y = 660
    p12x = 650
    p12y = 685
    p13x = 300
    p13y = 635
    p14x = 1100
    p14y = 635
    p15x = 50
    p15y = 80
    p16x = 880
    p16y = 635
    p17x = 1050
    p17y = 635  
    p18x = 430
    p18y = 75       
    p20x= 75
    p20y= 685
    # titles
    main_screen = tk.Tk()
    main_screen.title("Routing Optimization Tool")
    main_screen.geometry("1280x720")  # window size
    # Initialize the save_optimization checkbox variable
    save_optimization_var = tk.BooleanVar(value=False)  # Default value is False (unchecked)
    # title
    title = tk.Label(main_screen, text="Routing Optimization Tool", font=("Arial", 20, "bold"))
    title.place(x=p1x, y=p1y)
    # design_name_label
    design_name_raw = os.path.splitext(os.path.basename(zip_file_path))[0]
    design_name = re.sub(r'[\u200f\u200e\u202a-\u202e]', '', design_name_raw)
    # design_name_label = tk.Label(main_screen, text=f"Design Name: {design_name}", font=("Arial", 14))
    if DEBUG:
        design_name_label = tk.Label(main_screen, text="Design Name: DEBUG MODE", font=("Arial", 16), fg="red")
    else:
        design_name_label = tk.Label(main_screen, text=f"Design Name: {design_name}", font=("Arial", 16))
    design_name_label.place(x=p2x-100, y=45)
    # Signal selection
    signal_var = tk.StringVar()
    signal_dropdown = ttk.Combobox(main_screen, textvariable=signal_var, state="readonly", width=15)
    signal_dropdown.place(x=p3x, y=p3y)
    signal_label = tk.Label(main_screen, text="Select a signal to optimize:", font=("Arial", 12))
    signal_label.place(x=p4x, y=p4y)
    # red_dot_canvas
    red_dot_canvas = tk.Canvas(main_screen, width=20, height=20, bg="white", highlightthickness=0)
    red_dot_canvas.place(x=p8x - 25, y=p8y)  # Red point location
    red_dot_canvas.create_oval(5, 5, 15, 15, fill="blue", outline="blue")
    # red_description_label
    red_description_label = tk.Label(main_screen, text="Design point", font=("Arial", 12), justify="left")
    red_description_label.place(x=p8x, y=p8y)
    # blue_dot_canvas
    blue_dot_canvas = tk.Canvas(main_screen, width=20, height=20, bg="white", highlightthickness=0)
    blue_dot_canvas.place(x=p8x - 25, y=p8y + 25)  # Black point location
    blue_dot_canvas.create_oval(5, 5, 15, 15, fill="red", outline="red")
    # blue_description_label
    blue_description_label = tk.Label(main_screen, text="Steiner point", font=("Arial", 12), justify="left")
    blue_description_label.place(x=p8x, y=p8y + 25)
    # M1_canvas
    m1_canvas = tk.Canvas(main_screen, width=20, height=20, bg="white", highlightthickness=0)
    m1_canvas.place(x=p8x + 100+30, y=p8y)
    m1_canvas.create_line(0, 10, 20, 10, fill="purple", width=5)
    # M1_label
    m1_label = tk.Label(main_screen, text="M1 metal", font=("Arial", 12), justify="left")
    m1_label.place(x=p8x+125+30, y=p8y)
    # M2_canvas
    m2_canvas = tk.Canvas(main_screen, width=20, height=20, bg="white", highlightthickness=0)
    m2_canvas.place(x=p8x + 100 + 30, y=p8y + 25)
    m2_canvas.create_line(10, 0, 10, 20, fill="orange", width=5)
    # M2_label
    m2_canvas = tk.Label(main_screen, text="M2 metal", font=("Arial", 12), justify="left")
    m2_canvas.place(x=p8x + 125 + 30, y=p8y + 25)
    # capacitance_label
    capacitance_label = tk.Label(main_screen, text="Capacitance of metals: -", font=("Arial", 12))
    capacitance_label.place(x=p9x + 50, y=p9y)
    # resistance_label
    resistance_label = tk.Label(main_screen, text="Resistance of metals: -", font=("Arial", 12))
    resistance_label.place(x=p9x + 50, y=p12y)
    # runtime_label
    runtime_label = tk.Label(main_screen, text="Optimization Runtime: -", font=("Arial", 12))
    runtime_label.place(x=p20x, y=p20y)
    # design_points_label
    design_points_label = tk.Label(main_screen, text="Number of design points: -", font=("Arial", 12))
    design_points_label.place(x=p10x, y=p10y)
    # steiner_points_label
    steiner_points_label = tk.Label(main_screen, text="Number of Steiner points: -", font=("Arial", 12))
    steiner_points_label.place(x=p11x, y=p11y)
    # RSMT_length_label
    RSMT_length_label = tk.Label(main_screen, text="RSMT Length: -", font=("Arial", 12))
    RSMT_length_label.place(x=p13x + 50, y=p13y)
    # all_points_label
    all_points_label = tk.Label(main_screen, text="Number of all points: -", font=("Arial", 12))
    all_points_label.place(x=p12x, y=p12y)
    # input_files_frame
    input_files_frame = tk.Frame(main_screen)
    
    input_files_frame.place(x=p6x, y=p6y)
    input_files_label = tk.Label(input_files_frame, text="Input Files:", font=("Arial", 12, "bold"))
    input_files_label.pack(anchor="w", pady=5)
    #file_listbox = tk.Listbox(input_files_frame, width=50, height=3)
    file_listbox = tk.Listbox(input_files_frame, width=45, height=3)

    file_listbox.pack(pady=5)
    if DEBUG:
        input_files_frame.place_forget()
    # Click event on a list item
    def on_file_select(event):
        try:
            selected_index = file_listbox.curselection()  # Getting the index of the selected item
            if not selected_index:  # If no item is selected
                return
            selected_file = file_listbox.get(selected_index)
            open_file_content(selected_file)
        except Exception as e:
            showerror("Error", f"An error occurred: {e}")
    file_listbox.bind("<<ListboxSelect>>", on_file_select)
    # Displaying file names in the ZIP file
    file_list = extract_file_list(zip_file_path)
    for file_name in file_list:
        file_listbox.insert(tk.END, file_name)
    # dots plane
    # Drawing area (Canvas)
    canvas_width = 1150
    canvas_height = 480
    drawing_canvas = tk.Canvas(
        main_screen,
        width=canvas_width,
        height=canvas_height,
        bg="white",
        highlightthickness=2,
        highlightbackground="black"
    )
    drawing_canvas.place(x=p5x, y=p5y)
    # Drawing a coordinate system with a GRID
    grid_spacing = 10
    draw_axis_with_grid(drawing_canvas, canvas_width, canvas_height, grid_spacing)
    # buttons
    # view_signals_button
    view_signals_button = tk.Button(
        main_screen,
        text="View Signals Data",
        command=view_signals_data,
        font=("Arial", 12),
        bg="#2196F3",
        fg="white",
        activebackground="#1976D2",
        activeforeground="white",
        relief="raised",
        borderwidth=3
    )
    view_signals_button.place(x=p16x, y=p16y)
    # view_components_button
    view_components_button = tk.Button(
        main_screen,
        text="View Components Data",
        command=view_components_data,
        font=("Arial", 12),
        bg="#2196F3",
        fg="white",
        activebackground="#1976D2",
        activeforeground="white",
        relief="raised",
        borderwidth=3
    )
    view_components_button.place(x=p17x, y=p17y)
    # choose_another_design_button
    choose_design_button = tk.Button(
        main_screen,
        text="Choose Another Design",
        command=choose_another_design,
        font=("Arial", 12),
        bg="#FFC107",  # צבע צהוב/כתום
        fg="black",
        activebackground="#FFA000",
        activeforeground="white",
        relief="raised",
        borderwidth=3
    )
    choose_design_button.place(x=p18x, y=p18y)

    if DEBUG:
        view_signals_button.config(state="disabled", bg="gray")
        view_components_button.config(state="disabled", bg="gray")
        choose_design_button.config(state="disabled", bg="gray")
    # optimize_button
    optimize_button = tk.Button(
        main_screen,
        text="Optimize",
        command=optimize,
        font=("Arial", 12, "bold"),
        bg="tomato",
        fg="white",
        activebackground="orangered",
        activeforeground="white",
        relief="raised",
        borderwidth=3
    )
    optimize_button.place(x=p15x, y=p15y)
    # Add the checkbox for saving optimization files
    save_checkbox = tk.Checkbutton(
        main_screen,
        text="Save Optimization Files",
        variable=save_optimization_var,
        font=("Arial", 12)
    )
    save_checkbox.place(x=p7x+10, y=p7y)  # Adjust the position as needed

    verilog_content = extract_verilog_file(zip_file_path)
    def_content = extract_def_file(zip_file_path)
    lef_content = extract_lef_file(zip_file_path)
    if def_content and lef_content and verilog_content:
        if DEBUG:
            # במצב דיבאג לציור, המערך יתמלא בנקודות קבועות
            signals_array = test_cases
            signal_dropdown["values"] = list(signals_array.keys())
            if signals_array:
                signal_dropdown.current(0)  # בחירת האות הראשונה כברירת מחדל
            log_and_print("DEBUG mode: Initialized signals array with test_cases.txt.")
        else:
            # במצב רגיל, המערך יתמלא מהקבצים
            signals_array = build_signals_array(verilog_content, signal_dropdown)
        fill_pin_positions(def_content, signals_array)
        components_array = build_components_array(def_content)
        fill_components_array(lef_content, components_array)
        complete_signals_array(verilog_content, signals_array, components_array)
    else:
        showerror("Error", "Required DEF, LEF, or Verilog file not found in the ZIP archive.")
        return
    def on_signal_select(event=None):
        selected_signal = signal_var.get()
        if selected_signal in signals_array:
            signal_points = signals_array[selected_signal]["positions"]
            draw_signal_points(drawing_canvas, signal_points)
            design_points_label.config(text=f"Number of design points: {len(signal_points)}")
            RSMT_length_label.config(text=f"RSMT Length: -")
            steiner_points_label.config(text="Number of steiner points: -")
            all_points_label.config(text="Number of all points: -")
            capacitance_label.config(text="Capacitance of metals: -")
            resistance_label.config(text="Resistance of metals: -")
            runtime_label.config(text="Optimization Runtime: -")  

    signal_dropdown.bind("<<ComboboxSelected>>", on_signal_select)  # Defining an event for value change in the dropdown
    on_signal_select()  # Manually invoking the function to draw points for the first signal
    main_screen.mainloop()
    
def benchmark_test_cases_runtime():
    from collections import defaultdict

    runtimes_by_group = defaultdict(list)
    log_file = os.path.join(script_dir, "average_run_time_per_terminals_size.txt")

    with open(log_file, "w") as log:
        header = "Benchmarking RSMT Optimization Runtime per Group Size\n" + "=" * 55 + "\n"
        log.write(header)
        print(header)

        for test_name, test_data in test_cases.items():
            terminals = test_data["positions"]
            n = len(terminals)

            try:
                start = time.perf_counter()
                _ = compute_rsmt(terminals)  # Only interested in runtime
                end = time.perf_counter()
                runtime = end - start
                runtimes_by_group[n].append(runtime)

                line = f"{test_name}: n={n}, runtime={runtime:.6f} seconds\n"
                log.write(line)
                print(line, end="")  # avoid double newline
            except Exception as e:
                error_line = f"{test_name}: ERROR - {str(e)}\n"
                log.write(error_line)
                print(error_line, end="")

        footer = "\nAverage Runtime Per Group Size:\n" + "-" * 35 + "\n"
        log.write(footer)
        print(footer)

        for n in sorted(runtimes_by_group.keys()):
            avg_runtime = sum(runtimes_by_group[n]) / len(runtimes_by_group[n])
            avg_line = f"n={n}: {avg_runtime:.6f} seconds (from {len(runtimes_by_group[n])} tests)\n"
            log.write(avg_line)
            print(avg_line, end="")


# run
if DEBUG:
    predefined_zip_path = os.path.join(script_dir, "..", "Input_Files", "DEBUG_MODE", "DEBUG_MODE.zip")
    # predefined_zip_path = "/home/os/Downloads/geosteiner-5.3/Input_Files/DEBUG_MODE/DEBUG_MODE.zip"
    #predefined_zip_path = "/media/sf_OS/Steiner/Input_Files/16bit_shift_register_clk_not_in_line/16bit_shift_register.zip"
    # predefined_zip_path = "/media/sf_OS/Steiner/Input_Files/‏‏4bit_shift_register_clk_not_in_line/‏‏4bit_shift_register_clk_not_in_line.zip"
    # predefined_zip_path = "/media/sf_OS/Steiner/Input_Files/4bit_shift_register/4bit_shift_register.zip"
    # predefined_zip_path = "/media/sf_OS/Steiner/Input_Files/not(ab)+b\not(ab)+b.zip"
    # benchmark_test_cases_runtime() # Uncomment if we want to check test_cases.txt runtime
    open_main_screen(predefined_zip_path)  # Directly transitions to the main work screen with a predefined file
else:
    open_start_screen()  # Normal mode: Starts with the splash screen
