import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Source } from "./types";
export function useCapture(
  sources: Source[],
  setError: (value: string) => void,
) {
  const [sourceId, setSourceId] = useState(""),
    [live, setLive] = useState(false);
  const video = useRef<HTMLVideoElement>(null),
    stream = useRef<MediaStream | null>(null),
    running = useRef(false),
    captureGeneration = useRef(0);
  useEffect(() => {
    const expire = () => {
      running.current = false;
      captureGeneration.current++;
      stream.current?.getTracks().forEach((t) => t.stop());
      setLive(false);
    };
    window.addEventListener("auth-expired", expire);
    return () => {
      expire();
      window.removeEventListener("auth-expired", expire);
    };
  }, []);
  async function stop() {
    running.current = false;
    captureGeneration.current++;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    if (video.current) video.current.srcObject = null;
    setLive(false);
    if (sourceId)
      await api("/sources/" + sourceId + "/stop", { method: "POST" });
  }
  async function start() {
    if (!sourceId) throw new Error("Select a camera source first");
    const source = sources.find((s) => s.id === sourceId);
    if (source?.kind !== "browser") {
      await api("/sources/" + sourceId + "/start", { method: "POST" });
      setLive(true);
      return;
    }
    const media = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    try {
      await api("/sources/" + sourceId + "/start", { method: "POST" });
    } catch (e) {
      media.getTracks().forEach((t) => t.stop());
      throw e;
    }
    stream.current = media;
    running.current = true;
    setLive(true);
    const generation = ++captureGeneration.current;
    if (video.current) {
      video.current.srcObject = media;
      await video.current.play();
    }
    const canvas = document.createElement("canvas");
    let sequence = 0;
    const capture = async () => {
      if (!running.current || generation !== captureGeneration.current) return;
      try {
        if (video.current?.videoWidth) {
          canvas.width = video.current.videoWidth;
          canvas.height = video.current.videoHeight;
          canvas.getContext("2d")!.drawImage(video.current, 0, 0);
          const blob = await new Promise<Blob | null>((resolve) =>
            canvas.toBlob(resolve, "image/jpeg", 0.8),
          );
          if (blob)
            await api("/sources/" + sourceId + "/frames", {
              method: "POST",
              headers: {
                "Content-Type": "image/jpeg",
                "X-Sequence": String(sequence++),
                "X-Capture-Ms": String(performance.now()),
              },
              body: blob,
            });
        }
      } catch (e) {
        setError((e as Error).message);
        if (
          [401, 403, 409].includes((e as Error & { status: number }).status)
        ) {
          running.current = false;
          captureGeneration.current++;
          stream.current?.getTracks().forEach((t) => t.stop());
          stream.current = null;
          setLive(false);
        }
      }
      if (running.current && generation === captureGeneration.current)
        setTimeout(capture, 200);
    };
    capture();
  }
  return { video, sourceId, setSourceId, live, start, stop };
}
