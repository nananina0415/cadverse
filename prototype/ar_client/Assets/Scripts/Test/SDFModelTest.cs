using UnityEngine;

public class SDFModelTest : MonoBehaviour
{
    [Header("OBJ Mesh Files")]
    public GameObject baseObjFile;  
    public GameObject shaftObjFile;  

    void Start()
    {
        // ==================================================================================
        // 1. 루트 컨테이너 초기화 및 좌표계 보정
        //    - SDF: Z-up
        //    - Unity: Y-up
        // ==================================================================================
        GameObject root = new GameObject("SDF_Simulation_Root");
        root.transform.rotation = Quaternion.Euler(-90, 0, 0); 
        root.transform.position = new Vector3(0, 0, 1.0f); // AR 카메라 전방 1m 배치

        GameObject baseObj = null;
        GameObject shaftObj = null;

        // ==================================================================================
        // 2. Base 링크 생성 (Parent Link)
        // ==================================================================================
        if (baseObjFile != null)
        {
            baseObj = Instantiate(baseObjFile, root.transform);
            baseObj.name = "base";

            // SDF <pose> 데이터 적용
            baseObj.transform.localPosition = new Vector3(-0.019173f, 0.035670f, 0.053948f);
            baseObj.transform.localScale = Vector3.one * 0.001f; // mm -> m 단위 변환
            
            // Mass 적용 및 Static 처리
            Rigidbody rb = baseObj.AddComponent<Rigidbody>();
            rb.mass = 0.54997f;
            rb.isKinematic = true; // Base는 지면에 고정된 상태 유지
        }

        // ==================================================================================
        // 3. Shaft 링크 생성 (Child Link)
        // ==================================================================================
        if (shaftObjFile != null)
        {
            shaftObj = Instantiate(shaftObjFile, root.transform);
            shaftObj.name = "shaft";

            // SDF <pose> 데이터 적용
            shaftObj.transform.localPosition = new Vector3(-0.020661f, 0.035670f, 0.082284f);
            shaftObj.transform.localScale = Vector3.one * 0.001f;

            // Mass 적용 및 Dynamic 처리
            Rigidbody rb = shaftObj.AddComponent<Rigidbody>();
            rb.mass = 1.08933f;
            // isKinematic = false (기본값): 물리 연산에 의해 회전 가능
        }

        // ==================================================================================
        // 4. Joint 구성
        //    - Type: Revolute (Hinge)
        //    - Axis: X (1, 0, 0)
        // ==================================================================================
        if (baseObj != null && shaftObj != null)
        {
            // 하위 링크(Shaft)에 HingeJoint 컴포넌트 추가
            HingeJoint hinge = shaftObj.AddComponent<HingeJoint>();
            
            // 상위 링크(Base)의 Rigidbody와 물리적 연결
            hinge.connectedBody = baseObj.GetComponent<Rigidbody>();

            // 회전축 설정 (SDF Axis)
            hinge.axis = new Vector3(1, 0, 0);

            // 앵커(Anchor) 자동 보정 활성화
            hinge.autoConfigureConnectedAnchor = true;
        }
    }
}