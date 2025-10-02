# ... existing code ...
@api_bp.route("/api/free-agents")
def api_free_agents():
# ... existing code ...
        cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num,))
        week_info = cur.fetchone()
        week_dates = {'start': date.fromisoformat(week_info['start_date']), 'end': date.fromisoformat(week_info['end_date'])}

        # Get next week's dates for streaming potential
        next_week_info = None
        if week_num < 25: # Assuming 25 is the max week
            cur.execute("SELECT start_date, end_date FROM fantasy_weeks WHERE week_number = ?", (week_num + 1,))
            next_week_info = cur.fetchone()

        next_week_dates = None
        if next_week_info:
            next_week_dates = {'start': date.fromisoformat(next_week_info['start_date']), 'end': date.fromisoformat(next_week_info['end_date'])}

        cur.execute("SELECT team_tricode, schedule_json FROM team_schedules")
        schedules = {row['team_tricode']: json.loads(row['schedule_json']) for row in cur.fetchall()}

        my_totals, my_daily_lineups, _ = calculate_optimized_totals(my_roster, week_num, schedules, week_dates)
# ... existing code ...
                fa_team = fa_proj.get('team', 'N/A').upper()
                fa_schedule = schedules.get(fa_team, [])
                games_this_week = sum(1 for d_str in fa_schedule if week_dates['start'] <= date.fromisoformat(d_str) <= week_dates['end'])
                if games_this_week == 0: continue

                # Calculate next week's game days
                next_week_starts = []
                if next_week_dates:
                    fa_schedule_dates = [date.fromisoformat(d_str) for d_str in fa_schedule]
                    for d in fa_schedule_dates:
                        if next_week_dates['start'] <= d <= next_week_dates['end']:
                            next_week_starts.append(d.strftime('%a'))

                next_week_starts_sorted = sorted(next_week_starts, key=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].index)

                fa_data = { "name": fa['name'], "positions": ', '.join(fa['eligible_positions']), "team": fa_team, "per_game_projections": fa_proj, "weekly_impact_score": 0, "games_this_week": games_this_week, "start_days": [], "weekly_projections": {}, "availability": fa.get('availability', 'FA'), "next_week_starts": ', '.join(next_week_starts_sorted)}

                for stat, value in fa_proj.items():
                    if stat not in ['player_name', 'team', 'positions'] and value is not None:
# ... existing code ...
                            fa_data['weekly_impact_score'] += value
                    current_date += timedelta(days=1)

                if fa_data['weekly_impact_score'] > 0:
                    fa_data['suggested_drop'] = ideal_drop['name'] if ideal_drop else "N/A"
                    fa_data['start_days'] = ', '.join(sorted(fa_data['start_days'], key=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].index))
                    evaluated_fas.append(fa_data)

            except (KeyError, TypeError, ValueError) as e:
                print(f"Skipping FA {fa.get('name', 'Unknown')}. Error: {e}")
# ... existing code ...
