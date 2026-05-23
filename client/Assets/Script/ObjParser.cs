using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;

public static class ObjParser
{
    public static Mesh Parse(byte[] data)
    {
        var lines = Encoding.UTF8.GetString(data).Split('\n');

        var srcPos  = new List<Vector3>();
        var srcNorm = new List<Vector3>();
        var srcUV   = new List<Vector2>();

        var dstVerts = new List<Vector3>();
        var dstNorms = new List<Vector3>();
        var dstUVs   = new List<Vector2>();
        var tris     = new List<int>();
        var map      = new Dictionary<(int vi, int ti, int ni), int>();

        foreach (var raw in lines)
        {
            var line = raw.Trim();
            if (line.Length == 0 || line[0] == '#') continue;

            if (line.StartsWith("v "))
            {
                var t = Tok(line, 2);
                srcPos.Add(CoordConvert.FusionDirToUnity(F(t[0]), F(t[1]), F(t[2])));
            }
            else if (line.StartsWith("vn "))
            {
                var t = Tok(line, 3);
                srcNorm.Add(CoordConvert.FusionDirToUnity(F(t[0]), F(t[1]), F(t[2])));
            }
            else if (line.StartsWith("vt "))
            {
                var t = Tok(line, 3);
                srcUV.Add(new Vector2(F(t[0]), F(t[1])));
            }
            else if (line.StartsWith("f "))
            {
                var tokens = Tok(line, 2);
                var fv = new int[tokens.Length];
                for (int i = 0; i < tokens.Length; i++)
                    fv[i] = GetOrAdd(tokens[i], srcPos, srcNorm, srcUV,
                                     dstVerts, dstNorms, dstUVs, map);

                // Fan triangulation; reversed winding order (RH→LH coord change)
                for (int i = 1; i < fv.Length - 1; i++)
                {
                    tris.Add(fv[0]);
                    tris.Add(fv[i + 1]);
                    tris.Add(fv[i]);
                }
            }
        }

        var mesh = new Mesh();
        mesh.indexFormat = dstVerts.Count > 65535
            ? UnityEngine.Rendering.IndexFormat.UInt32
            : UnityEngine.Rendering.IndexFormat.UInt16;
        mesh.vertices  = dstVerts.ToArray();
        if (srcNorm.Count > 0) mesh.normals = dstNorms.ToArray();
        if (srcUV.Count   > 0) mesh.uv      = dstUVs.ToArray();
        mesh.triangles = tris.ToArray();
        if (srcNorm.Count == 0) mesh.RecalculateNormals();
        mesh.RecalculateBounds();
        return mesh;
    }

    static int GetOrAdd(string token,
        List<Vector3> srcPos, List<Vector3> srcNorm, List<Vector2> srcUV,
        List<Vector3> verts, List<Vector3> norms, List<Vector2> uvs,
        Dictionary<(int, int, int), int> map)
    {
        var parts = token.Split('/');
        int vi = ObjIdx(parts[0], srcPos.Count);
        int ti = parts.Length > 1 && parts[1].Length > 0 ? ObjIdx(parts[1], srcUV.Count)  : -1;
        int ni = parts.Length > 2 && parts[2].Length > 0 ? ObjIdx(parts[2], srcNorm.Count) : -1;

        var key = (vi, ti, ni);
        if (map.TryGetValue(key, out int idx)) return idx;

        idx = verts.Count;
        map[key] = idx;
        verts.Add(srcPos[vi]);
        norms.Add(ni >= 0 ? srcNorm[ni] : Vector3.zero);
        uvs.Add(ti >= 0 ? srcUV[ti] : Vector2.zero);
        return idx;
    }

    static string[] Tok(string line, int skip)
        => line.Substring(skip).Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);

    static float F(string s)
        => float.Parse(s, CultureInfo.InvariantCulture);

    static int ObjIdx(string s, int count)
    {
        int i = int.Parse(s, CultureInfo.InvariantCulture);
        return i < 0 ? count + i : i - 1;
    }
}
