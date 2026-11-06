"""Score the frozen 30-case baseline using its frozen rubric, without generating answers."""
import grade_agent_eightpapers_20261105 as g
from run_regression_baseline_20261106 import RUN, LIBRARY
g.RUN=RUN;g.LIBRARY=LIBRARY;g.OUT=RUN/'jev';g.PACK=RUN/'pack'
if __name__=='__main__':g.run()
