#This project uses GeoSteiner 5.3, developed by David M. Warme, Pawel Winter, and Martin Zachariasen.
#The software is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License,
#and is intended for non-commercial use only.
#The distribution includes third-party components such as triangle and lp_solve_2.3, 
#which are subject to their own licenses. This project does not use these components directly.
import os
import ctypes
import sys, ast
import itertools

script_dir = os.path.dirname(os.path.abspath(__file__))

# Load the GeoSteiner library (assumes libgeosteiner.so is in the current directory or library path)
try:
    gst_lib = ctypes.CDLL(os.path.join(script_dir, "..", "geosteiner-5.3", ".libs", "libgeosteiner.so"))
except OSError:
    gst_lib = ctypes.CDLL(os.path.join(script_dir, "..", "geosteiner-5.3", "libgeosteiner.so"))

# Define C function prototypes for the GeoSteiner functions we will use.
gst_lib.gst_open_geosteiner.restype = ctypes.c_int
gst_lib.gst_open_geosteiner.argtypes = []  # no arguments

gst_lib.gst_close_geosteiner.restype = ctypes.c_int
gst_lib.gst_close_geosteiner.argtypes = []  # no arguments

gst_lib.gst_open_lpsolver.restype = ctypes.c_int
gst_lib.gst_open_lpsolver.argtypes = []  # no arguments

gst_lib.gst_close_lpsolver.restype = ctypes.c_int
gst_lib.gst_close_lpsolver.argtypes = []  # no arguments

# gst_rsmt(int nterms, double* terms, double* length, int* nsps, double* sps, int* nedges, int* edges, int* status, gst_param_ptr param)
gst_lib.gst_rsmt.restype = ctypes.c_int
gst_lib.gst_rsmt.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.POINTER(ctypes.c_int),
    ctypes.c_void_p  # parameter set (NULL for default)
]

def compute_rsmt(terminals):
    """
    Compute the Rectilinear Steiner Minimal Tree (RSMT) for the given terminals using the FDP dynamic programming algorithm.
    Returns a tuple: (total_length, steiner_points_list, edges_list)
    """
    n = len(terminals)
    if n == 0:
        return 0.0, [], []
    if n == 1:
        # Only one terminal: no Steiner points or edges needed.
        return 0.0, [], []

    # Initialize GeoSteiner environment and LP solver
    if gst_lib.gst_open_geosteiner() != 0:
        raise RuntimeError("Could not open GeoSteiner library.")
    # Open LP solver (may be needed for solving Steiner tree problems)
    if gst_lib.gst_open_lpsolver() != 0:
        gst_lib.gst_close_geosteiner()
        raise RuntimeError("Could not open LP solver.")

    try:
        # Map each terminal index to its coordinate for easy lookup
        coords = terminals  # list of (x,y) tuples for terminals
        # Pre-allocate output buffers for GeoSteiner (maximum size needed for full set)
        max_term = n
        max_sps = max_term - 2 if max_term > 2 else 0  # max Steiner points for n terminals (n-2 for tree with all terminals)
        max_edges = 2 * max_term - 3 if max_term > 1 else 0  # max edges in a Steiner tree with n terminals

        # Allocate ctypes buffers for outputs
        length_buf = ctypes.c_double()
        nsps_buf = ctypes.c_int()
        nedges_buf = ctypes.c_int()
        # Allocate arrays for Steiner points and edges with maximum needed size
        sps_buf = (ctypes.c_double * (2 * max(max_sps, 1)))()  # at least length 1 to avoid zero-length array if no Steiner
        edges_buf = (ctypes.c_int * (2 * max(max_edges, 1)))()

        # Helper function to compute FullTree (optimal Steiner tree) for a given subset of terminals.
        def full_tree_cost(sub_indices):
            """
            Uses GeoSteiner to compute the optimal full Steiner tree for the terminals in sub_indices.
            Returns the tree length (float). (We will get actual Steiner points/edges later if needed.)
            """
            m = len(sub_indices)
            # Prepare input coordinate array for this subset
            terms_array_type = ctypes.c_double * (2 * m)
            terms_flat = []
            for idx in sub_indices:
                x, y = coords[idx]
                terms_flat.extend([float(x), float(y)])
            terms_array = terms_array_type(*terms_flat)
            # Call GeoSteiner's rectilinear SMT solver for this subset
            status_buf = ctypes.c_int()
            ret = gst_lib.gst_rsmt(
                m,
                terms_array,
                ctypes.byref(length_buf),
                ctypes.byref(nsps_buf),
                sps_buf,
                ctypes.byref(nedges_buf),
                edges_buf,
                ctypes.byref(status_buf),
                None  # default parameters
            )
            if ret != 0 or status_buf.value != 0:
                raise RuntimeError(f"GeoSteiner failed on subset {sub_indices}: status {status_buf.value}")
            # length_buf now holds the length of the optimal Steiner tree for this subset
            return length_buf.value

        # Dynamic programming table: use dictionary from subset mask to (cost, split_choice)
        # subset mask: integer with bits representing which terminals are in the subset.
        # split_choice: None if subset is best as a full tree, or a tuple (join_term, mask_F) if best obtained by splitting.
        dp_cost = {}
        dp_choice = {}

        # Base cases: cost of single-terminal subsets is 0 (no edges needed).
        for i in range(n):
            mask = 1 << i
            dp_cost[mask] = 0.0
            dp_choice[mask] = None  # no Steiner tree or split needed for single terminal

        # Compute cost for all subsets of size >= 2
        # Iterate by increasing subset size (cardinality)
        for m in range(2, n + 1):
            # Generate all subsets of size m
            for subset in itertools.combinations(range(n), m):
                subset_indices = list(subset)
                # Represent subset as bit mask
                mask = 0
                for i in subset_indices:
                    mask |= (1 << i)
                # Compute cost of best full Steiner tree for this subset
                best_cost = full_tree_cost(subset_indices)
                best_choice = None  # assume full tree is best until a better split is found

                # If subset size is 2, splitting doesn't apply (it would just yield the same edge), so skip splitting.
                if m >= 3:
                    # Consider splitting the subset into two parts that share a terminal 'i' (join point)
                    # Loop over each terminal i in the subset as a possible join point
                    for i in subset_indices:
                        i_bit = 1 << i
                        # Set of other terminals in C besides i, represented as mask
                        others_mask = mask & ~i_bit  # subset mask with i's bit turned off
                        if others_mask == 0:
                            continue  # no others, skip (shouldn't happen for m>=3)
                        # Enumerate all non-empty proper subsets F of "others"
                        submask = others_mask
                        while submask:
                            # Skip trivial splits where F is all or none (already ensured none by while condition, skip all)
                            if submask == others_mask:
                                # submask equals all others => other part would be just {i}, trivial split, skip it
                                submask = (submask - 1) & others_mask
                                continue
                            # Compute the complementary part (C - F) mask; it automatically includes i
                            part1_mask = submask | i_bit       # F plus i
                            part2_mask = mask & ~submask       # C minus F (includes i because submask had no i)
                            # Both part1_mask and part2_mask contain i as a member.
                            # Compute the cost of this split: sum of optimal costs of the two parts
                            cost1 = dp_cost.get(part1_mask)
                            cost2 = dp_cost.get(part2_mask)
                            if cost1 is None or cost2 is None:
                                # This should not happen if we are iterating in increasing order,
                                # because both part1 and part2 are smaller than C (due to F being a proper subset).
                                raise RuntimeError("DP subset ordering issue: missing cost for subset in split.")
                            split_cost = cost1 + cost2
                            if split_cost < best_cost:
                                best_cost = split_cost
                                best_choice = (i, submask)  # store split decision: join at i, F mask = submask (subset of others)
                            # Move to next submask of others_mask
                            submask = (submask - 1) & others_mask

                # Store the best cost and decision for this subset
                dp_cost[mask] = best_cost
                dp_choice[mask] = best_choice  # None if full tree, or tuple (join_index, F_mask) if split

        # The full set of all terminals (mask with n lowest bits = 1...1)
        full_mask = (1 << n) - 1
        total_length = dp_cost[full_mask]

        # Second pass: reconstruct Steiner points and edges of the optimal tree using dp_choice decisions
        steiner_points = []
        edges = []

        # Use a cache to store the actual tree (edges and steiner points) for any subset whose optimal solution is a full tree.
        # This avoids calling GeoSteiner repeatedly for the same subset during reconstruction.
        full_tree_cache = {}

        def reconstruct_tree(mask):
            """Recursively reconstruct the edges and Steiner points for the optimal tree of the subset represented by mask."""
            choice = dp_choice[mask]
            if choice is None:
                # No split was chosen, so this subset is handled as a full Steiner tree.
                # Use GeoSteiner to get the actual tree (Steiner points and edges) for this subset.
                if mask in full_tree_cache:
                    # If we already computed this subtree, reuse it
                    return full_tree_cache[mask]
                # Prepare coordinate list for this subset
                sub_indices = [idx for idx in range(n) if mask & (1 << idx)]
                m = len(sub_indices)
                terms_array_type = ctypes.c_double * (2 * m)
                terms_flat = []
                for idx in sub_indices:
                    x, y = coords[idx]
                    terms_flat.extend([float(x), float(y)])
                terms_array = terms_array_type(*terms_flat)
                status_buf = ctypes.c_int()
                ret = gst_lib.gst_rsmt(
                    m,
                    terms_array,
                    ctypes.byref(length_buf),
                    ctypes.byref(nsps_buf),
                    sps_buf,
                    ctypes.byref(nedges_buf),
                    edges_buf,
                    ctypes.byref(status_buf),
                    None
                )
                if ret != 0 or status_buf.value != 0:
                    raise RuntimeError(f"GeoSteiner failed to reconstruct subset {sub_indices}: status {status_buf.value}")
                # Extract Steiner point coordinates and edges from the result
                sp_count = nsps_buf.value
                subset_edges = []
                subset_steiner = []
                # Terminal indices in this subset are 0..m-1 (in the order of sub_indices),
                # Steiner points have indices m..m+sp_count-1.
                # Map local index to coordinate:
                def get_coord(local_idx):
                    if local_idx < m:
                        # It's one of the original terminals in this subset
                        orig_term_index = sub_indices[local_idx]
                        return coords[orig_term_index]
                    else:
                        # It's a Steiner point: index offset into sps array
                        si = local_idx - m
                        x_val = sps_buf[2 * si]
                        y_val = sps_buf[2 * si + 1]
                        return (x_val, y_val)
                # Each edge is given by two endpoint indices in the edges_buf
                edge_count = nedges_buf.value
                for e in range(edge_count):
                    u = edges_buf[2 * e]
                    v = edges_buf[2 * e + 1]
                    p1 = get_coord(u)
                    p2 = get_coord(v)
                    subset_edges.append((p1, p2))
                # Collect Steiner coordinates (global) from this subset
                for j in range(sp_count):
                    sx = sps_buf[2 * j]
                    sy = sps_buf[2 * j + 1]
                    subset_steiner.append((sx, sy))
                # Cache this result to avoid duplicate computation if this subset recurs
                full_tree_cache[mask] = (subset_edges, subset_steiner)
                return (subset_edges, subset_steiner)
            else:
                # The subset is optimally obtained by splitting at a terminal.
                join_index, F_mask = choice
                i_bit = 1 << join_index
                # Part1 = F U {i}, Part2 = C - F (includes i as well)
                part1_mask = F_mask | i_bit
                part2_mask = mask & ~F_mask
                # Recurse on each part
                edges1, steiners1 = reconstruct_tree(part1_mask)
                edges2, steiners2 = reconstruct_tree(part2_mask)
                # When merging, note that both parts share the join terminal (with index join_index).
                # We combine edges and Steiner points from both subtrees. The join terminal is a common point, 
                # but since we represent edges as coordinate pairs, it will naturally appear in both sets.
                # We ensure no duplicate Steiner points are introduced (duplicates will be filtered out later).
                combined_edges = edges1 + edges2
                combined_steiners = steiners1 + steiners2
                return combined_edges, combined_steiners

        # Reconstruct the full tree for the entire set
        final_edges, final_steiners = reconstruct_tree(full_mask)
        # Filter unique Steiner points and exclude any that coincide with original terminal coordinates
        term_set = set(coords)
        unique_steiners = []
        for sp in final_steiners:
            # Use a small epsilon tolerance for float comparisons (though Steiner points should lie on input grid exactly in rectilinear case)
            if tuple(sp) not in term_set and sp not in unique_steiners:
                unique_steiners.append(sp)
        # Also ensure edges are unique pairs (if duplicates occurred, remove duplicates). 
        # We can use a set for edges, but need to account for unordered pairs if any (though these are directed edges from solver? Usually each edge listed once).
        unique_edge_set = set()
        unique_edges = []
        for (p, q) in final_edges:
            # Use a frozenset of points to avoid orientation issues (edges are undirected)
            edge_key = frozenset([p, q])
            if edge_key not in unique_edge_set:
                unique_edge_set.add(edge_key)
                unique_edges.append((p, q))

        return total_length, unique_steiners, unique_edges

    finally:
        # Clean up: close LP solver and GeoSteiner environment
        gst_lib.gst_close_lpsolver()
        gst_lib.gst_close_geosteiner()

if __name__ == "__main__":
    # Parse input: either from command-line argument or use a hard-coded example.
    if len(sys.argv) > 1:
        # Expect a single argument that is a Python literal list of coordinates.
        try:
            terminals = ast.literal_eval(sys.argv[1])
        except Exception as e:
            print("Error: Unable to parse input coordinates list. Please provide a Python list, e.g. \"[(0,0),(10,0),(0,10)]\"")
            sys.exit(1)
    else:
        # Example usage (can be replaced by user input)
        terminals = [(0, 0), (0, 10), (5, 5)]  # Example terminals; modify this list as needed

    # Compute RSMT using FDP algorithm
    length, steiner_points, edges = compute_rsmt(terminals)
    # Output the results
    print("Terminals:", terminals)
    print("Total RSMT length:", length)
    print("Steiner points:", steiner_points)
    print("Edges:")
    for e in edges:
        print(f"  {e}")

