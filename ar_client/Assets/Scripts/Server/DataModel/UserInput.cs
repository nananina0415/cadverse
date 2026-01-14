using System;
using System.Collections.Generic;

namespace CADverse.Server.DataModel
{
    /// <summary>
    /// 클라이언트 → 서버: 유저 입력
    /// WebSocket을 통해 전송
    /// </summary>
    [Serializable]
    public class UserInput
    {
        /// <summary>
        /// 입력 타입: "click", "drag", "key" 등
        /// </summary>
        public string input_type;

        /// <summary>
        /// 입력 데이터 (타입에 따라 다름)
        /// </summary>
        public Dictionary<string, object> data;

        public UserInput(string inputType)
        {
            input_type = inputType;
            data = new Dictionary<string, object>();
        }
    }
}
