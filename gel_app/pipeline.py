"""라리화 배치는 실제 데이터 전용 파이프라인을 사용한다."""
from .live_pipeline import load_snapshot, run_batch

if __name__ == "__main__":
    run_batch(force=True)

