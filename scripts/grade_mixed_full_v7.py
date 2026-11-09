import grade_grounded_coverage_full as grading
grading.BASE=grading.ROOT/".rag-data/evaluations/specialists-three-suites-20261107/mixed-full-v7-20261109"
grading.OUT=grading.BASE/"mixed-jev-v1"
if __name__=="__main__": grading.main()
