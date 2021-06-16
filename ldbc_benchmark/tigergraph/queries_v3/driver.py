#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from timeit import default_timer as timer
import ast
import requests
import re
from datetime import datetime

def get_parser():
    query_help = 'Query numbers (default:"all"). A list split by comma e.g. "1,2", or "not:bi3,bi4" to exclude some queries, or "reg:[1-4]" to use a regular expression'	
    machine_dir_help = 'The machine (optional) and directory to load data from, e.g. "/home/tigergraph/data" or "ALL:/home/tigergraph/data"'
    parameter_help = 'Parameter file in json (default:parameters/sf1.json).'

    # The top-level parser.
    main_parser = argparse.ArgumentParser(description='Various utilities working with GSQL for LDBC SNB.')
    main_parser.set_defaults(func=lambda _: main_parser.print_usage())
    main_subparsers = main_parser.add_subparsers(dest='cmd')

    # ./driver.py load [schema/query/data] 
    load_parser = main_subparsers.add_parser('load', help='Load the schema, queries, or data')
    load_parser.set_defaults(func=lambda _: load_parser.print_usage())
    load_subparsers = load_parser.add_subparsers(dest='cmd_load')

    load_schema_parser = load_subparsers.add_parser('schema', help='Load the schema')
    load_schema_parser.set_defaults(func=cmd_load_schema)

    load_query_parser = load_subparsers.add_parser('query', help='Install queries')
    load_query_parser.add_argument('-q', '--queries', type=str, default='all', help=query_help)
    load_query_parser.set_defaults(func=cmd_load_query)
    # ./driver.py load data machine:dir 
    load_data_parser = load_subparsers.add_parser('data', help='Load data')
    load_data_parser.add_argument('machine_dir', type=str, help=machine_dir_help)
    load_data_parser.set_defaults(func=cmd_load_data)

    load_all_parser = load_subparsers.add_parser('all', help='Load the schema, queries, and data')
    load_all_parser.add_argument('machine_dir', type=str, help=machine_dir_help)
    load_all_parser.set_defaults(func=cmd_load_all)

    # ./driver.py run [-p parameter] [-q queries]
    run_parser = main_subparsers.add_parser('run', help='Run the workloads')
    run_parser.add_argument('-p', '--parameter', type=Path, default= Path('parameters/sf1.json'), help='Parameter file in json.')
    run_parser.add_argument('-q', '--queries', type=str, default='all', help=query_help)
    run_parser.add_argument('-n', '--nruns', type=int, default=1, help='number of runs')
    run_parser.set_defaults(func=cmd_run)

    # ./driver.py compare [-q queries]
    compare_parser = main_subparsers.add_parser('compare', help='Compare the results')
    compare_parser.add_argument('-q', '--queries', type=str, default='all', help=query_help)
    compare_parser.add_argument('-s', '--source', type=Path, default=Path('results'), help='direcotry of the source results (default: results)')
    compare_parser.add_argument('-t', '--target', type=Path, default=Path('cypher/results'), help='direcotry of the target results (default: cypher/results)')
    compare_parser.set_defaults(func=cmd_compare)
    
    # Running all from loading to running.
    all_parser = main_subparsers.add_parser('all', help='Do all of the above.')
    all_parser.add_argument('machine_dir', type=str, help='The machine and directory to load data from. "machine:data_dir"')
    all_parser.add_argument('-p', '--parameter', type=Path, default= Path('parameters/sf1.json'), help=parameter_help)
    all_parser.add_argument('-q', '--queries', type=str, default='', help=query_help)
    all_parser.set_defaults(func=cmd_all)

    return main_parser

def list2str(xs):
    return ','.join([str(x) for x in xs])

class ResultWithElapsed:
    def __init__(self, result, elapsed):
        self.result = result
        self.elapsed = elapsed


class Query:

    ENDPOINT = 'http://127.0.0.1:9000/query/ldbc_snb/'
    HEADERS = {'GSQL-TIMEOUT': '7200000'}

    def __init__(self, name, transform_parameter=None):
        self.name = name
        self.transform_parameter = transform_parameter

    def run(self, parameter):
        if self.transform_parameter is not None:
            parameter = self.transform_parameter(parameter)

        start = timer()
        response = requests.get(self.ENDPOINT + self.name, headers=self.HEADERS, params=parameter).json()
        end = timer()

        if response['error']:
            raise Exception(str(response['message']))

        return ResultWithElapsed(response['results'], end - start)


class Workload:
    def __init__(self, name, queries, transform_result):
        self.name = name
        self.queries = queries
        self.transform_result = transform_result

    def run(self, parameter):
        results = [query.run(parameter) for query in self.queries]
        result = self.transform_result([r.result for r in results])
        elapsed = sum(r.elapsed for r in results)
        return ResultWithElapsed(result, elapsed)

'''
def transform_parameter_bi1(parameter):
    return {'date': parameter['datetime']}
'''

class ResultTransform:
    def __init__(self):
        self.transforms = []

    def __call__(self, results):
        for transform in self.transforms:
            results = transform(results)
        return results

    def __getitem__(self, key):
        def transform_result(results):
            return results[key]
        self.transforms.append(transform_result)
        return self


    def change_key(self, key_map):
        def transform_result(results):
            return {key_map.get(k, k): v for k, v in results.items()}
        self.transforms.append(transform_result)
        return self


    def del_keys(self, keys):
        def transform_result(results):
            return [
                {k: v for k, v in result.items() if k not in keys}
                for result in results
            ]
        self.transforms.append(transform_result)
        return self

    def change_keys(self, key_map):
        def transform_result(results):
            return [
                {key_map.get(k, k): v for k, v in result.items()}
                for result in results
            ]
        self.transforms.append(transform_result)
        return self


DATA_NAMES = [
    'Comment',
    'Comment_hasCreator_Person',
    'Comment_hasTag_Tag',
    'Comment_isLocatedIn_Country',
    'Comment_replyOf_Comment',
    'Comment_replyOf_Post',
    'Forum',
    'Forum_containerOf_Post',
    'Forum_hasMember_Person',
    'Forum_hasModerator_Person',
    'Forum_hasTag_Tag',
    'Organisation',
    'Organisation_isLocatedIn_Place',
    'Person',
    'Person_hasInterest_Tag',
    'Person_isLocatedIn_City',
    'Person_knows_Person',
    'Person_likes_Comment',
    'Person_likes_Post',
    'Person_studyAt_University',
    'Person_workAt_Company',
    'Place',
    'Place_isPartOf_Place',
    'Post',
    'Post_hasCreator_Person',
    'Post_hasTag_Tag',
    'Post_isLocatedIn_Country',
    'Tag',
    'TagClass',
    'TagClass_isSubclassOf_TagClass',
    'Tag_hasType_TagClass',
]

SCRIPT_DIR_PATH = Path(__file__).resolve().parent
total = 21
WORKLOADS = [Workload(f'bi{i}', [Query(f'bi{i}')], ResultTransform()[0][0]['@@result']) for i in range(1,total)]
WORKLOADS[7] = Workload('bi8', [Query('bi8')], ResultTransform()[0][0]['@@result'].del_keys(['totalScore']))
WORKLOADS[9] = Workload('bi10', [Query('bi10')], ResultTransform()[0][0]['result'])
WORKLOADS[10] = Workload('bi11', [Query('bi11')], ResultTransform()[0][0])

'''Loads parameters for a given file'''
def load_allparameters(file):
    with open(file) as f: 
        txt = f.read().replace('\n','')
        return ast.literal_eval(txt)

def cmd_load_schema(args):
    '''Loads the schema.'''
    subprocess.run(['gsql', str(SCRIPT_DIR_PATH / 'schema.gsql')])

def cmd_load_query(args):
    '''Loads queries from the given workloads.'''
    gsql = ''

    for workload in args.workload:
        workload_path = (SCRIPT_DIR_PATH / 'queries' / f'{workload.name}.gsql').resolve()
        gsql += f'@{workload_path}\n'

    queries_to_install = [
        query.name
        for workload in args.workload
        for query in workload.queries
    ]
    gsql += f'INSTALL QUERY {", ".join(queries_to_install)}\n'

    subprocess.run(['gsql', '-g', 'ldbc_snb'], input=gsql.encode())

def cmd_load_csv(args):
    '''Loads data from the given data_dir path.'''
    file_paths = [(args.data_dir / name).with_suffix('.csv') for name in DATA_NAMES]
    gsql = 'RUN LOADING JOB load_ldbc_snb USING '
    gsql += ', '.join(f'file_{name}="{file_path}"' for name, file_path in zip(DATA_NAMES, file_paths))
    subprocess.run(['gsql', '-g', 'ldbc_snb', gsql])

def cmd_load_data(args):
    '''Loads data from the given data_dir path.'''
    if args.data_dir is None: 
        subprocess.run('RUN LOADING JOB load_ldbc_snb')
        return 

    file_paths = [(args.data_dir / name) for name in DATA_NAMES]
    gsql = 'RUN LOADING JOB load_ldbc_snb USING '
    gsql += ', '.join(f'file_{name}="{args.machine}{file_path}"' for name, file_path in zip(DATA_NAMES, file_paths))
    subprocess.run(['gsql', '-g', 'ldbc_snb', gsql])

def cmd_load_all(args):
    '''Loads the schema, data and queries.'''
    cmd_load_schema(args)
    cmd_load_data(args)
    cmd_load_query(args)


def median(time_list):
    return sorted(time_list)[len(time_list)//2]

def writeResult(result, filename):
    with open(filename, 'w') as f:
        if isinstance(result, dict): 
            f.write(str(list(result.values()))+'\n')
            return  
        for row in result:
            row = [v for k,v in row.items()]
            f.write(str(row)+'\n')
            
def cmd_run(args):
    os.makedirs('results',exist_ok=True)
    os.makedirs('elapsed_time',exist_ok=True)
    parameters = load_allparameters(args.parameter)
    parameters['bi1'] = {'date':parameters['bi1']['datetime']}
    print(f"run for {args.nruns} times ...")
    print("Q\tNrow\tMedian time\t")
    for workload in args.workload:
        time_list = []
        result = workload.run(parameters[workload.name])
        time_list.append(result.elapsed)    
        # write the query results to log/bi[1-20]
        result_file = Path('results')/ (workload.name+'.txt')  
        writeResult(result.result, result_file)
        with open(Path('elapsed_time')/ (workload.name+'.txt'), 'w') as f:
            f.write(str(result.elapsed))
        
        for i in range(args.nruns-1):
            result = workload.run(parameters[workload.name])
            time_list.append(result.elapsed)    
            with open(Path('elapsed_time')/ (workload.name+'.txt'), 'a') as f:
                f.write(','+str(result.elapsed))
        median_time = median(time_list)
        print(f'{workload.name}\t{len(result.result)}\t{median_time:.2f}')


def cmd_compare(args):
    for workload in args.workload:
        Pass = True
        file1 = args.source/(workload.name+'.txt')
        file2 = args.target/(workload.name+'.txt')
        if not file1.exists():
            print(f'{workload.name}: file {str(file1)} does not exist') 
            continue
        if not file2.exists():
            print(f'{workload.name}: file {str(file2)} does not exist') 
            continue        
        # compare number of lines
        if len(open(file1).readlines()) != len(open(file2).readlines()): 
            print(f'{workload.name}: number of lines is different') 
            continue

        with open(file1, 'r') as f1, open(file2, 'r') as f2:
            for i, (row1,row2) in enumerate(zip(f1,f2)):
                row1 = ast.literal_eval(row1) 
                row2 = ast.literal_eval(row2)
                if len(row1) != len(row2):
                    print(f'{workload.name} line {i}: number of columns are different {len(row1)} != {len(row2)}')
                    Pass = False

                for j, (col1,col2) in enumerate(zip(row1,row2)):
                    if (isinstance(col1, float) and abs(col1-col2)<1e-3):
                        continue
                    if isinstance(col1,str) and re.match("\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",col1):
                        t1 = datetime.strptime(col1, "%Y-%m-%d %H:%M:%S")
                        t2 = datetime.strptime(col2, "%Y-%m-%d %H:%M:%S")
                        if abs((t1-t2).total_seconds()) < 2:
                            continue
                    if col1!=col2:
                        print(f'{workload.name} line {i} column {j}: {col1} != {col2}')
                        Pass = False
                        break
                                        
                if not Pass: 
                    break
            if Pass: 
                print(f'{workload.name}: Pass')

def cmd_all(args):
    cmd_load_all(args)
    cmd_run(args)

def check_args(args):
    # Parse workload from string to a list 
    if args.cmd in ['load','run','compare','all'] or (args.cmd == 'load' and args.cmd_load in ['query','all']):
        # default is all the workloads
        all = [str(i) for i in range(1,total)]
        alls = set(all)
        if getattr(args, 'queries', 'all') == 'all':
            actual = alls
        # exclude cases
        elif args.queries.startswith('not:'):
            exclude = args.queries[4:].split(',')
            actual = alls - set(exclude)
        # regular expression
        elif args.queries.startswith('reg:'):
            r = re.compile(args.queries[4:])
            actual = list(filter(r.match, all))
        else:
            actual = set(args.queries.split(','))
        args.workload = [WORKLOADS[i-1] for i in range(1,total) if str(i) in actual]
        print('Workload:', list2str([w.name for w in args.workload]))
    
    #check mahine_dir
    if (args.cmd == 'load' and (args.cmd_load in ['csv','data','all']))  or args.cmd == 'all':
        missing = []
        if ':' in args.machine_dir:
            mds = args.machine_dir.split(':')
            if len(mds) != 2:
                raise Exception("<data_dir> should be in format: 'machine:data_dir'")
            args.machine =  mds[0] + ':'
            args.data_dir = Path(mds[1])
        else:
            args.machine, args.data_dir = '', Path(args.machine_dir)

        for name in DATA_NAMES:
            file_path = (args.data_dir / name)
            if args.cmd_load == 'csv': file_path = file_path.withsuffix('.csv')
            if args.machine in ['', 'ALL'] and not file_path.is_dir():
                missing.append(file_path.name)
            if args.machine in ['', 'ALL'] and args.cmd_load == 'csv' and not file_path.is_file():
                missing.append(file_path.name)
            
        if len(missing) > 0:
            raise ValueError(f'The directory "{args.data_dir}" is missing files/directory {", ".join(missing)}.')

def main():
    args = get_parser().parse_args()
    check_args(args)
    args.func(args)


if __name__ == '__main__':
    main()