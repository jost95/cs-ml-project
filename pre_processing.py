import os
import time
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler

from definitions import GEN_PATH
from utilities import helper as h


def process_matches(stats_filepath, proc_match_filepath, t_weights, base_weight, proc_years, t_levels, surfaces):
    # Generates a match matrix with certain statistics for each match
    print('----- GENERATING PRE-PROCESSED MATCHES -----')
    start_time = time.time()

    mutual_matches_clay = pd.read_hdf(stats_filepath, key='mm_clay')
    mutual_matches_grass = pd.read_hdf(stats_filepath, key='mm_grass')
    mutual_matches_hard = pd.read_hdf(stats_filepath, key='mm_hard')
    mutual_matches = mutual_matches_clay + mutual_matches_grass + mutual_matches_hard
    mutual_score = pd.read_hdf(stats_filepath, key='ms')
    cond_stats = pd.read_hdf(stats_filepath, key='cs')
    print('Generated statistics loaded')

    # Load rankings
    rankings = h.load_rankings()

    # Load raw_matches and sport by date
    print('Loading raw matches...')
    raw_matches = h.load_matches(proc_years)
    raw_matches.sort_values(by=['tourney_date'], inplace=True, ascending=True)

    # Load last years matches to calculate recent performance for matches in january
    last_year = proc_years['from'] - 1
    recent_years = {
        'from': last_year,
        'to': last_year
    }

    current_tourney_date = raw_matches.iloc[0].tourney_date
    month_offset = 3
    date_limit = current_tourney_date - pd.DateOffset(months=month_offset)

    print('Loading recent matches...')
    recent_matches = h.load_matches(recent_years)
    recent_matches = recent_matches.loc[recent_matches.tourney_date >= date_limit]

    # Load tournament details
    tourneys = pd.read_csv(os.path.join(GEN_PATH, 'tourneys_fixed.csv'), index_col=0)

    data_columns = ['tourney_date', 'rel_total_wins', 'rel_surface_wins', 'mutual_wins', 'mutual_surface_wins',
                    'mutual_games', 'rank_diff', 'points_grad_diff', 'home_advantage', 'rel_climate_wins',
                    'rel_recent_wins', 'rel_tourney_games', 'tourney_level', 'player_1', 'player_2', 'surface',
                    'age_diff', 'outcome']
    matches = np.zeros((len(raw_matches), len(data_columns)), dtype=np.int64)
    matches = pd.DataFrame(matches, columns=data_columns)

    i = 0
    no_matches = len(raw_matches)

    print('Pre-processing matches...')

    # Generate training matrix and update statistics matrices
    # Loop unavoidable
    for raw_match in raw_matches.itertuples():
        match = matches.iloc[i].copy()
        winner_id = raw_match.winner_id
        loser_id = raw_match.loser_id
        tourney_date = raw_match.tourney_date
        time_weight = h.get_time_weight(tourney_date)
        surface = h.get_surface(raw_match.surface)
        location = h.filter_tourney_name(raw_match.tourney_name)
        climate = tourneys.loc[tourneys.location == location, 'climate']

        if len(climate) > 0:
            climate = climate.iloc[0]
        else:
            # If climate unknown, assume tempered (maybe indoor)
            climate = 'tempered'

        # Update recent matches where tournament date is strictly larger one month ago
        if tourney_date > current_tourney_date:
            current_tourney_date = tourney_date
            date_limit = current_tourney_date - pd.DateOffset(months=month_offset)
            recent_matches = recent_matches.loc[recent_matches.tourney_date >= date_limit]

        # 1. Relative total win raw_matches differences
        rel_total_wins = h.get_relative_total_wins(cond_stats, winner_id, loser_id)
        match.rel_total_wins = round(base_weight * rel_total_wins)

        # 2. Relative surface win differences
        rel_surface_wins = h.get_relative_surface_wins(cond_stats, winner_id, loser_id, surface)
        match.rel_surface_wins = round(base_weight * rel_surface_wins)

        # 3. Mutual wins
        mutual_wins = mutual_matches[winner_id][loser_id] - mutual_matches[loser_id][winner_id]
        match.mutual_wins = mutual_wins

        # 4. Mutual surface wins
        mutual_surface_wins = h.get_mutual_surface_wins(mutual_matches_clay, mutual_matches_grass, mutual_matches_hard,
                                                        surface, winner_id, loser_id)
        match.mutual_surface_wins = mutual_surface_wins

        # 4. Mutual game
        mutual_games = mutual_score[winner_id][loser_id] - mutual_score[loser_id][winner_id]
        match.mutual_games = mutual_games

        # 5. Rank diff
        rank_diff, points_grad_diff = h.get_rankings(rankings, winner_id, loser_id, tourney_date)
        match.rank_diff = rank_diff
        match.points_grad_diff = points_grad_diff

        # 6. Home advantage
        home_advantage = h.get_home_advantage(raw_match.winner_ioc, raw_match.loser_ioc, tourneys,
                                              raw_match.tourney_name)
        match.home_advantage = home_advantage

        # 7. Relative climate win differences
        rel_climate_wins = h.get_relative_climate_wins(cond_stats, winner_id, loser_id, climate)
        match.rel_climate_wins = round(base_weight * rel_climate_wins)

        # 8. Get recent wins
        rel_recent_wins = h.get_recent_performance(winner_id, loser_id, recent_matches, tourney_date)
        match.rel_recent_wins = round(base_weight * rel_recent_wins)

        # 9. Get tournament performance in games
        tourney_id = raw_match.tourney_id
        match_num = raw_match.match_num
        rel_tourney_games = h.get_tourney_games(winner_id, loser_id, recent_matches, tourney_id, match_num)
        match.rel_tourney_games = rel_tourney_games

        # 10. Set age difference
        match.age_diff = raw_match.winner_age - raw_match.loser_age

        # 11. Winner is always winner
        match.outcome = 1

        # Create a balanced set with equal outcomes
        if i % 2 == 0:
            try:
                # An error here occured once and I am not sure why
                match = -match
            except TypeError:
                print(match)

        # 12. Set non numeric stuff after balancing set
        # Set the date as unix time so the store is more efficient (integer)
        match.tourney_date = int(tourney_date.timestamp())
        match.player_1 = winner_id
        match.player_2 = loser_id
        match.tourney_level = t_levels[raw_match.tourney_level]
        match.surface = surfaces[surface]

        # Update entry
        matches.iloc[i] = match

        # Add current match to recent matches
        # noinspection PyProtectedMember
        raw_match_df = pd.DataFrame.from_records([raw_match], columns=raw_match._fields, exclude=['Index'])
        recent_matches = recent_matches.append(pd.DataFrame(raw_match_df))

        # Update stats matrices
        match_d_weight = round(base_weight * time_weight)
        match_dt_weight = round(base_weight * time_weight * t_weights[raw_match.tourney_level])

        cond_stats['total_wins'][winner_id] += match_dt_weight
        cond_stats['surface_' + surface + '_wins'][winner_id] += match_d_weight
        cond_stats['climate_' + climate + '_wins'][winner_id] += match_d_weight
        cond_stats['total_losses'][loser_id] += match_dt_weight
        cond_stats['surface_' + surface + '_losses'][loser_id] += match_d_weight
        cond_stats['climate_' + climate + '_losses'][loser_id] += match_d_weight

        # Update mutual stats
        mutual_matches[winner_id][loser_id] += match_d_weight

        # Extract win on surface
        if surface == 'clay':
            mutual_matches_clay[winner_id][loser_id] += match_d_weight
        elif surface == 'grass':
            mutual_matches_grass[winner_id][loser_id] += match_d_weight
        else:
            mutual_matches_hard[winner_id][loser_id] += match_d_weight

        try:
            winner_games, loser_games = h.get_score(raw_match.score)
        except ValueError:
            winner_games = 0
            loser_games = 0

        mutual_score[winner_id][loser_id] += round(base_weight * time_weight * winner_games)
        mutual_score[loser_id][winner_id] += round(base_weight * time_weight * loser_games)

        # Update counter
        i += 1
        h.print_progress(i, no_matches)

    print('All', no_matches, 'matches (100%) processed')

    cols_not_scale = ['tourney_date', 'home_advantage', 'tourney_level', 'player_1', 'player_2', 'surface', 'outcome']
    matches_not_scale = matches.filter(cols_not_scale, axis=1)
    matches_scale = matches.drop(cols_not_scale, axis=1)
    matches_scale[matches_scale.columns] = StandardScaler().fit_transform(matches_scale[matches_scale.columns])
    matches = matches_scale.join(matches_not_scale)
    matches.to_hdf(proc_match_filepath, key='matches', mode='w')

    print('Pre-processed H5 matches saved')

    end_time = time.time()
    time_diff = round(end_time - start_time)
    print('----- PRE-PROCESS COMPLETED, EXEC TIME:', time_diff, 'SECONDS ----- \n')
