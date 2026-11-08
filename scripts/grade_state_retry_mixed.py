"""Grade only the two checkpoint-repair retries with the frozen Jev rubric."""
import grade_grounded_coverage_full as grading

grading.BASE=grading.ROOT/'.rag-data/evaluations/specialists-three-suites-20261107/state-retry-20261108'
grading.OUT=grading.BASE/'mixed-jev-v1'
if __name__=='__main__':grading.main()
