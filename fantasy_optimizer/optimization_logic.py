"""
Contains the core optimization logic for finding the best fantasy lineup.
This module is independent of Flask and handles the algorithmic parts of the application.
"""

def find_optimal_lineup(active_players, category_weights={}):
    """
    Determines the optimal fantasy lineup from a list of active players for a given day,
    based on their projected stats and provided category weights.

    This function uses a recursive approach with memoization (dynamic programming)
    to efficiently solve the roster-filling problem.

    Args:
        active_players (list): A list of player dictionaries, each containing their
                               projections and eligible positions.
        category_weights (dict): A dictionary mapping stat categories to their weights,
                                 used to calculate a player's marginal value.

    Returns:
        tuple: A tuple containing two lists:
               - The optimal roster (list of (player_dict, position_str) tuples).
               - The benched players (list of player_dict).
    """
    def safe_get_stat(player, stat_name):
        """Safely retrieves a player's projected stat, returning 0 if not found or invalid."""
        try:
            proj = player.get('per_game_projections', {})
            return float(proj.get(stat_name, 0))
        except (ValueError, TypeError):
            return 0

    def calculate_marginal_value(player, weights):
        """Calculates a single 'value' score for a player based on weighted categories."""
        if not weights:
            return safe_get_stat(player, 'pts')
        value = 0
        inverse_stats = ['ga']
        for stat, weight in weights.items():
            player_stat = safe_get_stat(player, stat)
            value += -player_stat * weight if stat in inverse_stats else player_stat * weight
        return value

    # Separate players who are on Injured Reserve
    ir_players = [p for p in active_players if 'IR' in p.get('positions', '') or 'IR+' in p.get('positions', '')]
    eligible_players = [p for p in active_players if p not in ir_players]

    # Calculate marginal value for each eligible player
    for p in eligible_players:
        p['marginal_value'] = calculate_marginal_value(p, category_weights)

    # Separate skaters and goalies
    eligible_skaters = [p for p in eligible_players if 'G' not in p.get('positions', '').split(', ')]
    eligible_goalies = [p for p in eligible_players if 'G' in p.get('positions', '').split(', ')]

    # Handle goalies separately: sort by wins and take the top 2
    eligible_goalies.sort(key=lambda p: safe_get_stat(p, 'w'), reverse=True)
    optimal_goalies = [(g, 'G') for g in eligible_goalies[:2]]
    benched_goalies = eligible_goalies[2:]

    # Sort skaters by their calculated marginal value to process best players first
    eligible_skaters.sort(key=lambda p: p.get('marginal_value', 0), reverse=True)

    # --- Recursive Solver for Skaters ---
    memo = {}
    ordered_skater_slots = ['C', 'LW', 'RW', 'D']

    def solve_skaters(player_index, slots_tuple):
        """Recursively finds the best combination of skaters to fill the remaining slots."""
        if player_index == len(eligible_skaters):
            return 0, []
        state = (player_index, slots_tuple)
        if state in memo:
            return memo[state]

        slots = dict(zip(ordered_skater_slots, slots_tuple))
        player = eligible_skaters[player_index]

        # Path 1: Skip the current player
        best_score, best_lineup = solve_skaters(player_index + 1, slots_tuple)

        # Path 2: Try to place the current player in each of their eligible slots
        player_positions = [p for p in player.get('positions', '').split(', ') if p in slots]
        for pos in player_positions:
            if slots[pos] > 0:
                new_slots = slots.copy()
                new_slots[pos] -= 1
                path_score, path_lineup = solve_skaters(player_index + 1, tuple(new_slots.values()))
                current_score = player.get('marginal_value', 0) + path_score

                if current_score > best_score:
                    best_score, best_lineup = current_score, [(player, pos)] + path_lineup

        memo[state] = (best_score, best_lineup)
        return best_score, best_lineup

    initial_skater_slots = {'C': 2, 'LW': 2, 'RW': 2, 'D': 4}
    _, optimal_skaters = solve_skaters(0, tuple(initial_skater_slots[s] for s in ordered_skater_slots))

    # Combine results and determine the final bench
    optimal_roster = optimal_skaters + optimal_goalies
    optimal_player_names = {p['name'] for p, pos in optimal_roster}
    benched_skaters = [p for p in eligible_skaters if p['name'] not in optimal_player_names]
    benched_players = benched_skaters + benched_goalies + ir_players

    return optimal_roster, benched_players
