using UnityEngine;

public static class CoordConvert
{
    // Fusion (X, Y, Z) cm → Unity (X, Z, Y) m
    public static Vector3 FusionToUnity(float fx, float fy, float fz)
        => new Vector3(fx * 0.01f, fz * 0.01f, fy * 0.01f);

    // Fusion direction vector → Unity direction (axis swap only, no scale)
    public static Vector3 FusionDirToUnity(float fx, float fy, float fz)
        => new Vector3(fx, fz, fy);

    // Row-major 16-element Fusion transform (cm) → Unity Matrix4x4 (m)
    // Input layout: [Xx,Xy,Xz,tx, Yx,Yy,Yz,ty, Zx,Zy,Zz,tz, 0,0,0,1]
    // M_Unity = P * M_Fusion * P  (P = Y↔Z axis swap); translation * 0.01
    public static Matrix4x4 FusionToUnity(float[] d)
    {
        var m = new Matrix4x4();
        m.m00 = d[0];  m.m01 = d[2];  m.m02 = d[1];  m.m03 = d[3]  * 0.01f;
        m.m10 = d[8];  m.m11 = d[10]; m.m12 = d[9];  m.m13 = d[11] * 0.01f;
        m.m20 = d[4];  m.m21 = d[6];  m.m22 = d[5];  m.m23 = d[7]  * 0.01f;
        m.m30 = 0f;    m.m31 = 0f;    m.m32 = 0f;    m.m33 = 1f;
        return m;
    }

    // Sim position [px,py,pz] m → Unity Vector3(px, pz, py) m (axis swap only)
    public static Vector3 SimPosToUnity(float[] pos)
        => new Vector3(pos[0], pos[2], pos[1]);

    // Sim rotation [rw,rx,ry,rz] → Unity Quaternion(-rx, -rz, -ry, rw)
    // Y↔Z swap changes handedness (RH→LH), reversing rotation direction → negate xyz
    public static Quaternion SimRotToUnity(float[] rot)
        => new Quaternion(-rot[1], -rot[3], -rot[2], rot[0]);

    // Unity Vector3(ux, uy, uz) → Sim [ux, uz, uy] (axis swap only)
    public static float[] UnityPosToSim(Vector3 p)
        => new float[] { p.x, p.z, p.y };

    // Unity direction (ux, uy, uz) → Sim [ux, uz, uy] (axis swap, no scale)
    public static float[] UnityDirToSim(Vector3 d)
        => new float[] { d.x, d.z, d.y };
}
