# self_compention_tof

RB10 로봇의 self-only ToF 데이터로 기준 모델을 만들고, 현재 ToF 측정값이
`SELF`, `EXTERNAL_CANDIDATE`, `EXTERNAL_CONFIRMED`, `UNCERTAIN`
중 무엇인지 판정하는 패키지입니다.

현재 패키지는 다음 흐름으로 사용합니다.

1. self-only txt 데이터셋으로 기준 모델 생성
2. 저장된 모델로 새 데이터 또는 기록된 txt를 replay 하면서 분류


## 0. 패키지 설치 전 / 설치 후 차이

README 안에 명령이 두 가지 형태로 나오는 이유는,
이 패키지를 아직 설치하지 않은 상태에서도 바로 실행할 수 있게 해두었기 때문입니다.

### 설치 없이 실행

예:

```bash
PYTHONPATH=/home/song/rb10_Proximity/src/self_compention_tof \
python3 -m self_compention_tof.build_self_model ...
```

이 방식은 소스 폴더를 직접 Python import 경로에 넣어서 실행합니다.

장점:

- 패키지 설치 없이 바로 테스트 가능
- 코드 수정 후 바로 다시 실행 가능
- 개발 중 가장 편함

단점:

- 매번 `PYTHONPATH=...` 를 붙여야 함
- 터미널 위치나 환경에 따라 import 경로를 신경써야 함


### 설치 후 실행

예:

```bash
ros2 run self_compention_tof build_tof_self_model ...
ros2 run self_compention_tof replay_tof_classifier ...
```

이 방식은 패키지를 시스템 또는 워크스페이스에 설치한 뒤,
`ros2 run`으로 실행하는 방식입니다.

장점:

- 명령이 짧고 깔끔함
- `PYTHONPATH`를 매번 안 붙여도 됨
- ROS/colcon 환경에서 쓰기 편함

단점:

- 코드 수정 후 다시 설치하거나 다시 source 해야 할 수 있음


### 언제 어느 쪽을 쓰면 되나

- 개발 중이고 코드를 자주 바꾸는 중이면:
  설치 없이 실행 추천
- 기능이 어느 정도 안정됐고 반복 실행만 할 거면:
  설치 후 실행 추천


### 핵심 차이 한 줄 요약

- 설치 없이 실행: "소스 코드 폴더를 직접 실행"
- 설치 후 실행: "설치된 명령어 이름으로 실행"


## 1. 데이터 형식

`dataset/*.txt` 파일은 아래 같은 형식을 사용합니다.

```text
# Data format:
# timestamp, j1, j2, j3, j4, j5, j6, jv1, ..., prox1..8, raw1..8, tof1..8
```

이 패키지는 여기서 주로 아래 값을 사용합니다.

- `j1 ~ j6`: 현재 관절각
- `tof1 ~ tof8`: 각 센서의 ToF 거리

현재 기본 설정은 `q2, q3, q4`를 사용합니다.


## 2. 핵심 개념

모델은 센서별로 joint space 상의 기준점들을 저장합니다.

각 기준점에는 아래 정보가 들어갑니다.

- `q_center`: 해당 기준 영역의 중심 joint 값
- `mu_self`: self-only 상태에서의 평균 ToF
- `std_self`: self-only 상태에서의 표준편차
- `n_samples`: 샘플 수
- `d_low`, `d_high`: Student-t 기반 self-only prediction interval
- `support_radius`: 이 기준점이 유효하다고 보는 joint-space 반경

온라인 판정 시에는 현재 `q_now`와 가장 가까운 기준점을 찾고,
현재 `tof_now`가 하한 기준보다 충분히 작으면 외부 물체 후보로 보고,
그 외에는 `SELF`로 둡니다.
`UNCERTAIN`은 주로 support 밖인 경우에만 사용합니다.


## 3. 빠른 사용 순서

### 3-1. 모델 만들기

아래 예시는 센서 `3, 4, 6, 7`에 대해 `q2, q3, q4`를 사용해서 모델을 만듭니다.

설치 없이 바로 실행하려면:

```bash
PYTHONPATH=/home/song/rb10_Proximity/src/self_compention_tof \
python3 -m self_compention_tof.build_self_model \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[1]dataset_50_25_new.txt' \
  --sensor-ids 3 4 6 7 \
  --q-use-dims q2 q3 q4 \
  --method grid \
  --grid-resolution 5 5 5 \
  --min-samples 5 \
  --alpha 0.05 \
  --support-margin 5.0
```

패키지를 설치한 뒤에는:

```bash
ros2 run self_compention_tof build_tof_self_model \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[1]dataset_50_25_new.txt' \
  --sensor-ids 3 4 6 7 \
  --q-use-dims q2 q3 q4 \
  --method grid \
  --grid-resolution 5 5 5 \
  --min-samples 5
```

성공하면 기본적으로 패키지의 `dataset` 폴더 안에
`tof_self_model.json` 파일이 생성됩니다.

예:

- [dataset/tof_self_model.json](/home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_self_model.json)

다른 위치에 저장하고 싶으면 `--output`으로 직접 경로를 지정하면 됩니다.

여러 개 self-only txt를 한 번에 같이 쓰는 것도 가능합니다.

- `--file`를 여러 번 주기:

```bash
ros2 run self_compention_tof build_tof_self_model \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[1]dataset_50_25_new.txt' \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[2]dataset_50_25_new.txt' \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[3]dataset_100_25_new.txt' \
  --sensor-ids 3 4 6 7 \
  --q-use-dims q2 q3 q4
```

- `dataset` 폴더 안의 모든 txt를 한 번에 쓰기:

```bash
ros2 run self_compention_tof build_tof_self_model \
  --dataset-dir /home/song/rb10_Proximity/src/self_compention_tof/dataset \
  --all \
  --sensor-ids 3 4 6 7 \
  --q-use-dims q2 q3 q4
```

- 특정 패턴만 골라서 쓰기:

```bash
ros2 run self_compention_tof build_tof_self_model \
  --dataset-dir /home/song/rb10_Proximity/src/self_compention_tof/dataset \
  --pattern '*new.txt' \
  --pattern '*hist.txt' \
  --sensor-ids 3 4 6 7 \
  --q-use-dims q2 q3 q4
```

실행하면 실제로 어떤 txt 파일들이 모델에 들어갔는지 콘솔에 같이 출력됩니다.


### 3-2. 분류 replay 해보기

저장한 모델을 사용해서 txt를 다시 읽고 프레임별로 분류합니다.

설치 없이 바로 실행:

```bash
PYTHONPATH=/home/song/rb10_Proximity/src/self_compention_tof \
python3 -m self_compention_tof.replay_classifier \
  --model /tmp/tof_self_model.json \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[1]dataset_50_25_new.txt' \
  --sensor-ids 3 4 6 7 \
  --q-query-radius 5.0 \
  --ext-margin 20.0 \
  --self-margin 5.0 \
  --n-on 3 \
  --n-off 3 \
  --limit 20
```

패키지 설치 후:

```bash
ros2 run self_compention_tof replay_tof_classifier \
  --model /home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_self_model.json \
  --file /home/song/rb10_Proximity/src/self_compention_tof/dataset/'[1]dataset_50_25_new.txt' \
  --sensor-ids 3 4 6 7
```

출력에는 각 시점에서 센서별 label이 보이고,
기본적으로 패키지의 `dataset` 폴더 안에 `tof_replay.csv`도 저장됩니다.

예:

- [dataset/tof_replay.csv](/home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_replay.csv)

다른 위치에 저장하고 싶으면 `--output-csv`를 직접 지정하면 됩니다.


### 3-3. replay 결과를 그림으로 보기

CSV 대신 그림으로 보려면 replay 결과를 바로 plot 할 수 있습니다.

설치 없이 바로 실행:

```bash
PYTHONPATH=/home/song/rb10_Proximity/src/self_compention_tof \
python3 -m self_compention_tof.plot_replay \
  --csv /home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_replay.csv
```

패키지 설치 후:

```bash
ros2 run self_compention_tof plot_tof_replay \
  --csv /home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_replay.csv
```

기본적으로 아래 PNG도 저장됩니다.

- [dataset/tof_replay_plot.png](/home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_replay_plot.png)

이 그림에는 아래 정보가 같이 들어갑니다.

- 진한 선: 실제 ToF 측정값
- 파란 점선: `mu_self`
- 하늘색 밴드: `d_low ~ d_high` prediction band
- 회색 점선: external 판정에 쓰는 lower threshold (`d_low - ext_margin`)
- 색 점:
  - 초록 `SELF`
  - 주황 `UNCERTAIN`
  - 빨강 `EXTERNAL_CANDIDATE`
  - 진한 빨강 `EXTERNAL_CONFIRMED`

창을 띄우지 않고 PNG만 만들고 싶으면 `--no-show`를 쓰면 됩니다.


### 3-4. 실시간 ROS2 inference

실시간에서는 `/joint_states`와 `/tof_distance{sensor_id}` 토픽을 받아서
즉시 `SELF / EXTERNAL / UNCERTAIN` 판정을 할 수 있습니다.

입력 토픽 기본값:

- `/joint_states` : `sensor_msgs/JointState`
- `/tof_distance3`, `/tof_distance4`, `/tof_distance6`, `/tof_distance7` : `sensor_msgs/Range`

실행 예:

```bash
ros2 run self_compention_tof realtime_tof_self_infer \
  --ros-args \
  -p model_path:=/home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_self_model.json \
  -p sensor_ids:="[3,4,6,7]" \
  -p q_query_radius:=5.0 \
  -p ext_margin:=20.0 \
  -p n_on:=3 \
  -p n_off:=3
```

출력 토픽:

- `/tof_self_classifier/external_detected` : `std_msgs/Bool`
  - 하나라도 external candidate/confirmed이면 `true`
- `/tof_self_classifier/label_codes` : `std_msgs/Int32MultiArray`
  - 센서 순서대로 label code를 발행
  - `0=SELF`, `1=EXTERNAL_CANDIDATE`, `2=EXTERNAL_CONFIRMED`, `3=UNCERTAIN`
- `/tof_self_classifier/result_json` : `std_msgs/String`
  - 센서별 ToF, label, threshold, deviation score를 JSON 문자열로 발행

추천:

- 제어/안전 정지에는 `/tof_self_classifier/external_detected`
- 디버깅/시각화/로그에는 `/tof_self_classifier/result_json`
- 경량 후처리에는 `/tof_self_classifier/label_codes`

기본값은 제어용만 publish 하도록 되어 있습니다.

- `publish_external_detected = true`
- `publish_label_codes = false`
- `publish_result_json = false`

디버그용 출력까지 켜고 싶으면 예를 들어 이렇게 실행하면 됩니다.

```bash
ros2 run self_compention_tof realtime_tof_self_infer \
  --ros-args \
  -p model_path:=/home/song/rb10_Proximity/src/self_compention_tof/dataset/tof_self_model.json \
  -p publish_label_codes:=true \
  -p publish_result_json:=true
```


## 4. 주요 옵션 설명

### 모델 생성 관련

- `--file`
  사용할 txt 파일 경로입니다. 여러 번 넣으면 여러 파일을 합쳐서 모델을 만듭니다.
- `--dataset-dir`
  `--file`을 안 쓸 때 txt 파일을 찾을 폴더입니다.
- `--sensor-ids`
  모델을 만들 센서 번호입니다. 예: `3 4 6 7`
- `--q-use-dims`
  사용할 관절 차원입니다. 예: `q2 q3 q4`, `2 3 4`
- `--method`
  기준점 생성 방식입니다.
  - `grid`: joint space를 bin으로 나누어 통계 생성
  - `knn_reference`: 반경 기반으로 reference 그룹 생성
- `--grid-resolution`
  `grid` 방식에서 각 joint 차원의 bin 크기입니다. 단위는 degree입니다.
- `--min-samples`
  한 reference entry를 만들기 위한 최소 샘플 수입니다.
- `--alpha`
  prediction interval 유의수준입니다. 작게 할수록 band가 넓어집니다.
- `--support-margin`
  reference가 유효한 joint-space 반경입니다.
- `--min-tof`, `--max-tof`
  유효한 ToF 값 범위를 제한할 때 사용합니다.


### 온라인 분류 관련

- `--q-query-radius`
  현재 joint 상태가 가장 가까운 reference와 너무 멀면 `UNCERTAIN` 처리합니다.
- `--ext-margin`
  `d_low`보다 얼마나 더 작아야 외부 물체 후보로 볼지 정하는 여유값입니다.
  크게 하면 external 오탐이 줄고, 작게 하면 더 민감해집니다.
- `--self-margin`
  현재 lower-bound-only 분류에서는 직접 사용하지 않습니다.
  인자 호환성을 위해 남겨둔 값입니다.
- `--n-on`
  `EXTERNAL_CONFIRMED`로 확정되기 위한 연속 프레임 수입니다.
- `--n-off`
  다시 `SELF`로 돌아오기 위한 연속 프레임 수입니다.


## 5. 추천 시작값

처음에는 아래 설정으로 시작하는 것을 권장합니다.

- `q_use_dims = [q2, q3, q4]`
- `method = grid`
- `grid_resolution = [5, 5]`
- `min_samples = 20`
- `alpha = 0.05`
- `support_margin = 5.0`
- `q_query_radius = 5.0`
- `ext_margin = 20.0`
- `self_margin = 0.0`
- `n_on = 3`
- `n_off = 3`

지금 기본값은 `q4`까지 포함한 3차원 joint reference입니다.


## 6. 파이썬 코드에서 직접 사용하기

```python
from self_compention_tof.dataset_io import load_self_only_samples
from self_compention_tof.model import (
    build_tof_self_model,
    classify_tof,
    create_hysteresis_states,
)

samples = load_self_only_samples(
    [
        "/home/song/rb10_Proximity/src/self_compention_tof/dataset/[1]dataset_50_25_new.txt"
    ],
    sensor_ids=[3, 4, 6, 7],
)

model = build_tof_self_model(
    self_only_dataset=samples,
    q_use_dims=["q2", "q3", "q4"],
    method="grid",
    grid_resolution=[5.0, 5.0, 5.0],
    min_samples=5,
    alpha=0.05,
    support_margin=5.0,
)

states = create_hysteresis_states([3, 4, 6, 7])

label, info = classify_tof(
    q_now=[86.2, -30.0, -103.0, 82.1, -88.7, 0.0],
    tof_now=1600.0,
    sensor_id=3,
    model=model,
    q_use_dims=["q2", "q3", "q4"],
    hysteresis_state=states[3],
    q_query_radius=5.0,
    ext_margin=20.0,
    self_margin=0.0,
    n_on=3,
    n_off=3,
)

print(label)
print(info)
```


## 7. 코드 위치

- 모델 생성/분류 핵심 로직:
  [self_compention_tof/model.py](/home/song/rb10_Proximity/src/self_compention_tof/self_compention_tof/model.py)
- txt 데이터 로딩:
  [self_compention_tof/dataset_io.py](/home/song/rb10_Proximity/src/self_compention_tof/self_compention_tof/dataset_io.py)
- 모델 생성 CLI:
  [build_self_model.py](/home/song/rb10_Proximity/src/self_compention_tof/self_compention_tof/build_self_model.py)
- replay CLI:
  [replay_classifier.py](/home/song/rb10_Proximity/src/self_compention_tof/self_compention_tof/replay_classifier.py)


## 8. 참고 사항

- 현재 txt 데이터에는 원래 `valid` 플래그가 없어서, 패키지 내부에서는 ToF 값이 정상 범위에 있으면 `valid=True`로 처리합니다.
- `grid` 방식이 먼저 쓰기 쉽고 결과 해석도 편합니다.
- `knn_reference`는 자세 분포가 고르지 않을 때 유용할 수 있습니다.
- 센서별로 self 분포가 다르므로, 반드시 센서별 모델을 따로 사용하는 것이 좋습니다.
