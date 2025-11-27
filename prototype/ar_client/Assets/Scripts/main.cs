using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
using CADverse.Communication;

public class Main : MonoBehaviour
{
    [Header("Server")]
    [SerializeField] private SimServer simServer;

    [Header("AR Components")]
    [SerializeField] private ARPlaneManager arPlaneManager;
    [SerializeField] private ARRaycastManager arRaycastManager;
    [SerializeField] private Camera arCamera;

    [Header("Debug")]
    [SerializeField] private bool useQrScan = false;
    [SerializeField] private string debugServerAddress = "192.168.0.1:8000/cadverse";

    private CompositeModel _loadedModel;
    private bool _isModelPlaced = false;
    private List<ARRaycastHit> _raycastHits = new List<ARRaycastHit>();

    async void Start()
    {
        Debug.Log("[Main] App started");

        simServer.OnConnected += HandleServerConnected;
        simServer.OnDisconnected += HandleServerDisconnected;
        simServer.OnError += HandleServerError;

        if (useQrScan)
        {
            Debug.Log("[Main] Starting QR scan");
            simServer.ConnectByQrScan();
        }
        else
        {
            Debug.Log("[Main] Debug mode: " + debugServerAddress);
            simServer.ConnectByQrCode(debugServerAddress);
        }
    }

    private async void HandleServerConnected()
    {
        Debug.Log("[Main] Server connected, downloading model");

        try
        {
            _loadedModel = await simServer.LoadModel();
            Debug.Log("[Main] Model loaded: " + _loadedModel.GetPartCount() + " parts");

            PlaceModelAtCenter();
        }
        catch (Exception ex)
        {
            Debug.LogError("[Main] Model load failed: " + ex.Message);
        }
    }

    private void HandleServerDisconnected()
    {
        Debug.LogWarning("[Main] Server disconnected");
    }

    private void HandleServerError(string error)
    {
        Debug.LogError("[Main] Server error: " + error);
    }

    void Update()
    {
        if (_loadedModel != null && simServer.IsConnected)
        {
            UpdateModelState();
        }

        if (!_isModelPlaced && _loadedModel != null && Input.touchCount > 0)
        {
            Touch touch = Input.GetTouch(0);
            if (touch.phase == TouchPhase.Began)
            {
                TryPlaceModelOnPlane(touch.position);
            }
        }

        if (_isModelPlaced && Input.touchCount > 0)
        {
            Touch touch = Input.GetTouch(0);
            if (touch.phase == TouchPhase.Began)
            {
                SendUserInputToServer(touch.position);
            }
        }
    }

    private void UpdateModelState()
    {
        var states = simServer.GetLatestModelState();

        for (int i = 0; i < states.Count && i < _loadedModel.GetPartCount(); i++)
        {
            GameObject part = _loadedModel.GetPart(i);
            if (part != null)
            {
                part.transform.localPosition = states[i].pos;
                part.transform.localRotation = states[i].GetQuaternion();
            }
        }
    }

    private void PlaceModelAtCenter()
    {
        if (_loadedModel == null) return;

        Vector3 position = arCamera.transform.position + arCamera.transform.forward * 2f;
        _loadedModel.transform.position = position;
        _loadedModel.transform.rotation = Quaternion.identity;

        Debug.Log("[Main] Model placed at center: " + position);
    }

    private void TryPlaceModelOnPlane(Vector2 touchPosition)
    {
        if (arRaycastManager == null || _loadedModel == null) return;

        if (arRaycastManager.Raycast(touchPosition, _raycastHits, TrackableType.PlaneWithinPolygon))
        {
            Pose hitPose = _raycastHits[0].pose;

            _loadedModel.transform.position = hitPose.position;
            _loadedModel.transform.rotation = hitPose.rotation;

            _isModelPlaced = true;
            Debug.Log("[Main] Model placed on plane: " + hitPose.position);
        }
    }

    private void SendUserInputToServer(Vector2 touchPosition)
    {
        if (_loadedModel == null) return;

        Ray ray = arCamera.ScreenPointToRay(touchPosition);

        if (Physics.Raycast(ray, out RaycastHit hit))
        {
            Vector3 point = hit.point;
            Vector3 direction = ray.direction.normalized;

            simServer.SendUserInput(point, direction);
            Debug.Log("[Main] User input sent: point=" + point + ", direction=" + direction);
        }
    }

    void OnDestroy()
    {
        if (simServer != null)
        {
            simServer.OnConnected -= HandleServerConnected;
            simServer.OnDisconnected -= HandleServerDisconnected;
            simServer.OnError -= HandleServerError;
        }
    }
}
