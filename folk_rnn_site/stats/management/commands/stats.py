#!/usr/local/bin/python3.6

import sys
import re
import ast
from datetime import datetime, timedelta
from collections import namedtuple, Counter
from statistics import mean, pstdev

from django.core.management.base import BaseCommand
from django.conf import settings

from archiver.models import Tune

Datum = namedtuple('Datum', ['date', 'session', 'info'])
generate_keys = ['model', 'temp', 'seed', 'key', 'meter', 'start_abc']
export_keys = ['play', 'download', 'archive']

verbose = False

class Command(BaseCommand):
    '''
    Collates and analyses useage data from logs and database. A Django management command.
    i.e `python3.6 /vagrant/folk_rnn_webapp/folk_rnn_site/manage.py stats`
        
    Includes utility functions, typically for interactive use, i.e.
        cd /folk_rnn_webapp/folk_rnn_site
        python3.6
        from backup.management.commands.stats import Command
        data = ingest_file(<path to composer.use.log>)
        print(session_view(data))
    '''
    help = 'Produce usage statistics suitable for academic write-up.'
    
    def handle(self, *args, **options):
        '''
        Process the command (i.e. the django manage.py entrypoint)
        '''
        composer_use_log_path = settings.LOGGING['handlers']['file_composer_use']['filename']
        
        data = ingest_file(composer_use_log_path)
        
        data = coalesce_continuous_sessions(data)
        
        tunes = tune_view_with_archiver_info(data)
        for tune, info in tunes.items():
            print(f'tune {tune}: {info}')
            
        sessions = session_view(data)
        for session, info in sessions.items():
            
            print(f'Session {session} ----------')
            for entry in info:
                print(entry)
            print()
        
        analyse(data, tunes, sessions)

def ingest_file(log_filepath, start_date=datetime(year=2018, month=5, day=19)):
    '''
    Read the composer use log from file, process into python objects, return a list of Datums
    2018-05-19 is when machinefolk went live, with a datamigration snafu that overwrote folkrnn tunes from 15-18th.
    '''
    with open(log_filepath, 'r') as f:
        data = []
        for line in f:
            date_field, time_field, session_field, info_field = line.rstrip().split(' ', 3)
            date = datetime.strptime(f'{date_field} {time_field}', '%Y-%m-%d %H:%M:%S,%f')
            if date < start_date:
                continue
            session = int(session_field)
            info = None
            if info_field == 'Connect':
                info = {'session': 'connect'}
            elif info_field == 'Disconnect':
                info = {'session': 'disconnect'}
            elif info_field.startswith('URL'): # URL: /tune/103. State: {'model': 'thesession_with_repeats.pickle', 'temp': '1.42', 'seed': '875453', 'key': 'K:Cmin', 'meter': 'M:4/4', 'start_abc': '', 'tunes': ['102', '103']}
                try:
                    state_dict = {'url_tune': int(re.match(r"URL: /tune/(\d+)\.", info_field).group(1))}
                except:
                    state_dict = {'url_tune': None} # URL: /
                try:
                    state_literal = re.search(r"State: ({.*})$", info_field).group(1)
                    state_dict.update(ast.literal_eval(state_literal))
                except Exception as e:
                    # Because I am over cautious I fucked this, and the field as logged was truncated to 400chars.
                    candidate = None
                    state_literal = re.search(r"State: ({.*)$", info_field).group(1)
                    while candidate is None:
                        end_idx = state_literal.rfind(',')
                        if end_idx == -1:
                            break
                        state_literal = state_literal[:end_idx] + '}'
                        try:
                            candidate = ast.literal_eval(state_literal)
                            if verbose:
                                print(f'Extracted {candidate} from malformed \n{info_field}\n')
                        except:
                            pass
                    if verbose and candidate is None:
                        print(f'Failed to extract from malformed \n{info_field}\n')
                    state_dict.update(candidate)
                info = {'state': state_dict}
            elif info_field.startswith('Compose command.'): # Compose command. Tune 103 created.
                tune_int = int(info_field.split(' ')[3])
                info = {'tune': tune_int, 'action': 'compose'}
            elif info_field.startswith('Compose command '): # Compose command data had errors: <ul class="errorlist"><li>start_abc<ul class="errorlist"><li>Invalid ABC as per RNN model</li></ul></li></ul>'
                pass
            elif info_field.startswith('Generate'): # Generate finish for tune 103
                pass
            elif info_field.startswith('Show'): # Show tune 103
                pass
            elif info_field.startswith('Hide'): # Hide tune 103
                pass
            elif info_field.startswith('midi_play'): # midi_play of tune 103
                try:
                    tune_int = int(info_field.split(' ')[3])
                except:
                    tune_int = None
                info = {'tune': tune_int, 'action': 'play'}
            elif info_field.startswith('midi_download'): # midi_download of tune 103
                try:
                    tune_int = int(info_field.split(' ')[3])
                except:
                    tune_int = None
                info = {'tune': tune_int, 'action': 'download'}
            elif info_field.startswith('tempo'): # tempo change to 94 of tune 103
                try:
                    tune_int = int(info_field.split(' ')[6])
                    tempo_int = int(info_field.split(' ')[3])
                except:
                    tune_int = None
                    tempo_int = None
                info = {'tune': tune_int, 'action': 'tempo', 'tempo': tempo_int}
            else:
                print(f'Unknown info field: {info_field}')
            if info:
                data.append(Datum(date, session, info))
    return data

def coalesce_continuous_sessions(data):
    '''
    Many sessions appear continuations of prior sessions, e.g. identical state
    This returns re-written data with the continuer session ids as the original id
    '''
    session_rewrite = {}
    last_state = {}
    for datum in data:
        state = datum.info.get('state')
        if state:
            if datum.session not in last_state.keys():
                for k, v in last_state.items():
                    if v == state['seed']:
                        session_rewrite[datum.session] = k
                        break
            last_state[session_rewrite.get(datum.session, datum.session)] = state['seed']
    new_data = []
    for datum in data:
        try:
            session = session_rewrite[datum.session]
            new_data.append(Datum(datum.date, session, datum.info))
        except KeyError:
            new_data.append(datum)
    if verbose:
        for datum in new_data:
            try:
                print(f"{datum.session}: {datum.info['state']['seed']}, {datum.info['state']['tunes']}")
            except KeyError:
                pass
    return new_data
    
def tune_view(data):
    '''
    Produce a tune-centric view of the data
    Per-session, track changes in the generate parameters *before* generate tune command
    Log actions on the tune after generation
    Return counts of all these things, e.g.
        tune: 9625: {'compose': 1}
        tune: 9626: {'compose': 1, 'play': 1}
        tune: 9627: {'start_abc': 25, 'compose': 1, 'download': 1}
        tune: 9628: {'compose': 1, 'download': 1}
        tune: 9629: {'compose': 1}
        tune: 9630: {'download': 2, 'compose': 1}
        tune: 9631: {'seed': 1, 'start_abc': 1, 'temp': 1, 'compose': 1, 'download': 1}
    '''
    tunes = {}
    session_state = {}
    session_changes = {}
    for datum in data:
        state = datum.info.get('state')
        if state:
            # determine the generate parameter changes before the tune is generated
            if datum.session not in session_state:
                session_changes[datum.session] = Counter()
                session_state[datum.session] = datum.info
            new_generate_params = {k: v for k,v in datum.info['state'].items() if k in generate_keys}
            old_generate_params = {k: v for k,v in session_state[datum.session]['state'].items() if k in generate_keys}
            changes = dict(set(new_generate_params.items()) - set(old_generate_params.items()))
            session_changes[datum.session].update(changes.keys())
            session_state[datum.session] = datum.info
            continue
        tune = datum.info.get('tune')
        if tune:
            if tune not in tunes:
                tunes[tune] = Counter()
                if datum.session in session_state:
                    tunes[tune].update(session_changes[datum.session])
                    del session_state[datum.session]
            tunes[tune][datum.info['action']] +=1
            continue
    return tunes

def tune_view_with_archiver_info(data):
    '''
    As per tune_view, but including data harvested from the archiver database.
    e.g. has each tune been archived
    '''
    tunes = tune_view(data)
    for composer_tune_id in tunes:
        if Tune.objects.filter(rnn_tune__id=composer_tune_id).exists():
            tunes[composer_tune_id]['archive'] +=1
    return tunes

def session_view(data):
    '''
    Produce a session-centric view of the data
    Return session history, e.g.
        Session 8144 ----------
        {'tune': 9600, 'action': 'compose'}
        {'seed': '467042'}
        {'tune': 9600, 'action': 'play'}
        {'tune': 9600, 'action': 'download'}
        {'temp': '1'}
        {'temp': '1.01'}
        {'temp': '1.02'}
        {'temp': '1.03'}
    '''
    def get_time_elapser():
        '''
        Track when a day or more passes between session entries
        '''
        last_datum = {}
        def time_elapsed(datum):
            info = None
            if datum.session in last_datum:
                elapsed_time = datum.date - last_datum[datum.session].date
                if elapsed_time > timedelta(days=1):
                    info = f'...{elapsed_time.days} day(s) pass...'
            last_datum[datum.session] = datum
            return info
        return time_elapsed
    def get_tune_archive_tracker():
        '''
        Track when generation parameters are reset (i.e. browse to /) or set by an archive tune (i.e. browse to /tune/x)
        This isn't logged directly (oh, hindsight) and so here follows some fragile heuristics
        '''
        current_tunes = {}
        def tune_archiver_tracked(datum):
            info = None
            if datum.session not in current_tunes:
                current_tunes[datum.session] = set()
            action = datum.info.get('action')
            if action == 'compose':
                current_tunes[datum.session].add(datum.info['tune'])
            state = datum.info.get('state')
            if state:
                if state['url_tune'] is None:
                    if 'session' not in state:
                        info = 'Generation parameters reset'
                elif state['url_tune'] not in current_tunes[datum.session]:
                    print(state['url_tune'], current_tunes[datum.session], state.get('tunes'))
                    info = f"Generation parameters set from archived tune {state['url_tune']}"
                    if 'tunes' in state: # not always there due to truncation
                        current_tunes[datum.session] = set(map(int, state['tunes']))
            return info
        return tune_archiver_tracked   
    def get_state_tracker():
        '''
        Track generation parameter state to return changes in that state
        '''
        last_state = {}
        def state_tracked(datum):
            info = None
            state = datum.info.get('state')
            if state:
                if datum.session not in last_state:
                    last_state[datum.session] = datum.info['state']
                new_generate_params = {k: v for k,v in state.items() if k in generate_keys}
                old_generate_params = {k: v for k,v in last_state[datum.session].items() if k in generate_keys}
                changes = dict(set(new_generate_params.items()) - set(old_generate_params.items()))
                if changes:
                    info = changes
                last_state[datum.session] = state
            return info
        return state_tracked
    sessions = {}
    time_elapsed = get_time_elapser()
    state_tracked = get_state_tracker()
    tune_archive_tracked = get_tune_archive_tracker()
    for datum in data:
        if datum.session not in sessions:
            sessions[datum.session] = []
        elapsed_info = time_elapsed(datum)
        if elapsed_info is not None:
            sessions[datum.session].append(elapsed_info)
        state_info = state_tracked(datum)
        if state_info:
            sessions[datum.session].append(state_info)
        tune_archived = tune_archive_tracked(datum)
        if tune_archived:
            sessions[datum.session].append(tune_archived)
        tune = datum.info.get('tune')
        if tune:
            sessions[datum.session].append(datum.info)
    return sessions

def analyse(data, tunes, sessions):
    '''
    We are interested in seeing:
    - What is the distribution of tunes generated in a session?
    - How often do users change parameters?
    - How many generated tunes are downloaded?
    - Is there a correlation between download and tweaking parameters, as in, Is the probability of download greater if the user tweaked the parameters. (Some users appear to have downloaded two or more times without generating anything new.)
    - Of the tunes downloaded, are there any common characteristics, like most of the tunes are in 6/8, Cmaj? 
    '''
    
    def format_dict(d):
        return ', '.join([f'{k}: {v:.2}' for k, v in d.items()])
    
    duration = data[-1].date - data[0].date
    session_tunes = {k: [info['tune'] for info in v if isinstance(info, dict) and info.get('action') == 'compose'] for k, v in sessions.items()}
    session_tune_counts = {k: len(v) for k, v in session_tunes.items()}
    print(f"{len(tunes)} tunes were generated from {len(session_tunes)} sessions over {duration.days} days.")
    print(f"Distribution: {sorted(Counter(session_tune_counts.values()).items())}")
    print(f"With mean: {mean(session_tune_counts.values()):.2} and standard deviation: {pstdev(session_tune_counts.values()):.2}")
    print()
    
    generating_session_tunes = {k: v for k, v in session_tunes.items() if v}
    generating_session_tune_counts = {k: len(v) for k, v in generating_session_tunes.items()}
    print("A session is more-or-less the use of a unique browser, tracked over time. However the number of sessions with no tunes generated may have little value, as some sessions reported as distinct were identifiably not, and not all visits to the site may have been made in good faith (e.g. bots). Our best approximation of good-faith users are then joining sessions that are identifiably continuations of previous ones, and then discounting any that did not generate a tune.")
    print(f"Our best approximation of good-faith users generated on average mean: {mean(generating_session_tune_counts.values()):.2} standard deviation: {pstdev(generating_session_tune_counts.values()):.2}.")
    print("For each tune generated, the frequency of the following generate parameters being used was:")
    print(format_dict({k: mean([k in tune for tune in tunes.values()]) for k in generate_keys}))
    print("For each tune generated, the frequency of it being played, downloaded or archived was:")
    print(format_dict({k: mean([k in tune for tune in tunes.values()]) for k in export_keys}))
    print("If the tune had no changes to the generate parameters, the frequency of it being played, downloaded or archived was:")
    no_changes = {k: mean([k in tune for tune in tunes.values() if set(tune.keys()).intersection(generate_keys) == set()]) for k in export_keys}
    no_changes.update({'all': mean([set(export_keys).intersection(tune.keys()) != set() for tune in tunes.values() if set(tune.keys()).intersection(generate_keys) == set()])})
    print(format_dict(no_changes))
    print("Whereas if the tune did have changes to the generate parameters, the frequency of it being played, downloaded or archived was:")
    changes = {k: mean([k in tune for tune in tunes.values() if set(tune.keys()).intersection(generate_keys) != set()]) for k in export_keys}
    changes.update({'all': mean([set(export_keys).intersection(tune.keys()) != set() for tune in tunes.values() if set(tune.keys()).intersection(generate_keys) != set()])})
    print(format_dict(changes))
    
    # TODO: extract ABC properties
    
if __name__ == '__main__':
    
    if sys.version_info.major < 3 or (sys.version_info.major == 3 and sys.version_info.minor < 6):
        sys.exit('Requires python 3.6 or higher')
    
    if (len(sys.argv) < 2):
        sys.exit('Missing log file')
        
    data = ingest_file(sys.argv[1])
    
    data = coalesce_continuous_sessions(data)
    
    tunes = tune_view(data)
    for tune, info in tunes.items():
        print(f'tune {tune}: {info}')
        
    sessions = session_view(data)
    for session, info in sessions.items():
        
        print(f'Session {session} ----------')
        for entry in info:
            print(entry)
        print()
    
    analyse(data, tunes, sessions)
    