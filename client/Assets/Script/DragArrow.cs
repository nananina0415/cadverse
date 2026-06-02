using UnityEngine;

namespace Cadverse
{
    // Drag 모드 터치 중 화면에 표시되는 화살표.
    // 시작점은 터치 시작 시 raycast hit.point에 고정되고,
    // 끝점은 시작점을 지나고 현재 카메라 forward에 수직인 평면과 ray의 교차점.
    // 평면이 매 프레임 폰 화면에 평행하게 갱신된다.
    //
    // 사용 흐름:
    //   var arrow = DragArrow.Create();
    //   arrow.Show(hitPoint);                  // 터치 시작
    //   Vector3 tip = arrow.UpdateTip(currentRay); // 터치 이동, tip을 시뮬 finger로도 사용
    //   arrow.Hide();                          // 터치 종료
    //   arrow.DestroyArrow();                  // 정리
    public class DragArrow : MonoBehaviour
    {
        const float ShaftWidth = 0.004f;   // m
        const float HeadLength = 0.02f;    // m
        const float HeadWidth  = 0.012f;   // m

        LineRenderer _shaft;
        LineRenderer _head;
        Vector3      _start;

        public static DragArrow Create()
        {
            var go    = new GameObject("DragArrow");
            var arrow = go.AddComponent<DragArrow>();
            arrow._shaft = MakeLine(go, "Shaft", ShaftWidth);
            arrow._head  = MakeLine(go, "Head",  HeadWidth);
            arrow.gameObject.SetActive(false);
            return arrow;
        }

        static LineRenderer MakeLine(GameObject parent, string name, float width)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent.transform, false);
            var lr = go.AddComponent<LineRenderer>();
            lr.useWorldSpace  = true;
            lr.positionCount  = 2;
            lr.startWidth     = width;
            lr.endWidth       = width;
            lr.material       = new Material(Shader.Find("Sprites/Default"));
            lr.startColor     = Color.yellow;
            lr.endColor       = Color.yellow;
            return lr;
        }

        public void Show(Vector3 start)
        {
            _start = start;
            _shaft.SetPosition(0, _start);
            _shaft.SetPosition(1, _start);
            _head.SetPosition(0, _start);
            _head.SetPosition(1, _start);
            gameObject.SetActive(true);
        }

        // 시각화의 끝점(tip)을 반환 — SimulationManager가 이걸 그대로 시뮬 finger로 전송해
        // 화면에 보이는 화살표와 시뮬에 적용되는 force vector를 일치시킨다.
        // 평면 평행/뒤쪽 케이스에서는 _start를 반환해 spring 길이 0으로 안전 fallback.
        public Vector3 UpdateTip(Ray currentRay)
        {
            var cam = Camera.main;
            Vector3 n = cam != null ? cam.transform.forward : Vector3.forward;

            float denom = Vector3.Dot(n, currentRay.direction);
            if (Mathf.Abs(denom) < 1e-6f) return _start;

            float t = Vector3.Dot(n, _start - currentRay.origin) / denom;
            if (t < 0f) return _start;

            Vector3 tip = currentRay.origin + currentRay.direction * t;
            Vector3 dir = tip - _start;
            float   len = dir.magnitude;
            if (len < 1e-6f)
            {
                _shaft.SetPosition(1, _start);
                _head.SetPosition(0, _start);
                _head.SetPosition(1, _start);
                return tip;
            }

            float shaftLen = Mathf.Max(0f, len - HeadLength);
            Vector3 shaftEnd = _start + dir.normalized * shaftLen;
            _shaft.SetPosition(0, _start);
            _shaft.SetPosition(1, shaftEnd);
            _head.SetPosition(0, shaftEnd);
            _head.SetPosition(1, tip);
            return tip;
        }

        public void Hide() => gameObject.SetActive(false);

        public void DestroyArrow()
        {
            if (this != null && gameObject != null)
                Destroy(gameObject);
        }
    }
}
