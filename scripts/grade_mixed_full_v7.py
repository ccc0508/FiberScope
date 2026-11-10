import argparse
import re
import grade_grounded_coverage_full as grading

if __name__=="__main__":
    parser=argparse.ArgumentParser(description='Grade a saved mixed evaluation run with Jev.')
    parser.add_argument('--run', default='mixed-full-v7-20261109')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',args.run):
        parser.error('Invalid run ID')
    grading.BASE=grading.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107'/args.run
    grading.OUT=grading.BASE/'mixed-jev-v1'
    grading.main()
