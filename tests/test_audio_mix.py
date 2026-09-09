"""BGM を敷く関門のテスト。

ここで守りたいのは1つだけ: **ナレーションが BGM に埋もれないこと**。
「聞いてみて良かった」は根拠にならないので、実際に ffmpeg で書き出した
音源を ebur128 で測った値で判定する。
"""

import subprocess

import pytest

from scripts import audio_mix
from scripts.audio_mix import (BGM_BELOW_VOICE_LU, MIN_SEPARATION_LU,
                               Loudness, NarrationBuried, bgm_gain_db,
                               final_gain_db, parse_loudness)


# ---------------------------------------------------------------- 純関数

def test_BGMはナレーションから決められた距離だけ下に置かれる():
    voice = Loudness(integrated=-24.5, true_peak=-6.8)
    bgm = Loudness(integrated=-13.0, true_peak=-1.2)

    gain = bgm_gain_db(voice, bgm)

    # -13.0 の素材を -24.5 - 18.0 = -42.5 に持っていく
    assert gain == pytest.approx(-29.5)


def test_素材が静かでもBGMは同じ距離に置かれる():
    """素材のラウドネスが違っても、行き先（voice から 18 LU 下）は変わらない。

    BGM を差し替えたときにゲインを定数で持っていると、静かな曲では
    聞こえず、大きい曲ではナレーションを潰す。行き先を実測から決める。
    """
    voice = Loudness(integrated=-24.5, true_peak=-6.8)

    loud = bgm_gain_db(voice, Loudness(integrated=-8.0, true_peak=-0.5))
    quiet = bgm_gain_db(voice, Loudness(integrated=-30.0, true_peak=-12.0))

    assert (-8.0 + loud) == pytest.approx(-30.0 + quiet)
    assert (-8.0 + loud) == pytest.approx(-24.5 - BGM_BELOW_VOICE_LU)


def test_最終ゲインは目標ラウドネスまでの差():
    assert final_gain_db(Loudness(integrated=-24.5, true_peak=-6.8)) == \
        pytest.approx(10.5)


# ---------------------------------------------------------------- 関門

def test_分離比が下限を割ったら止める():
    """ナレーションが埋もれた動画は成立しないので、警告ではなく例外。

    尺のズレ（verify_duration）は警告で通しているが、こちらは通さない。
    """
    voice = Loudness(integrated=-24.5, true_peak=-6.8)
    bed = Loudness(integrated=-24.5 - (MIN_SEPARATION_LU - 0.1),
                   true_peak=-12.0)

    with pytest.raises(NarrationBuried):
        audio_mix.assert_narration_audible(voice, bed)


def test_分離比が下限ちょうどなら通す():
    voice = Loudness(integrated=-24.5, true_peak=-6.8)
    bed = Loudness(integrated=-24.5 - MIN_SEPARATION_LU, true_peak=-12.0)

    audio_mix.assert_narration_audible(voice, bed)      # 例外が出なければよい


def test_設計値は下限より余裕がある():
    """18 LU 下に置く設計と 15 LU の下限が逆転していないこと。

    片方だけ動かすと、設計どおり作った動画が毎回関門で止まる（または
    関門が形だけになる）。
    """
    assert BGM_BELOW_VOICE_LU > MIN_SEPARATION_LU


# ---------------------------------------------------------------- 実測の解釈

def test_ebur128の出力からラウドネスとピークを読む():
    stderr = """[Parsed_ebur128_0 @ 0000] Summary:

  Integrated loudness:
    I:         -24.5 LUFS
    Threshold: -34.8 LUFS

  Loudness range:
    LRA:         2.1 LU
    Threshold: -44.8 LUFS
    LRA low:   -25.8 LUFS
    LRA high:  -23.8 LUFS

  True peak:
    Peak:       -6.8 dBFS
"""
    got = parse_loudness(stderr)

    assert got.integrated == pytest.approx(-24.5)
    assert got.true_peak == pytest.approx(-6.8)


def test_無音を測ったら読めなかったとして止める():
    """ebur128 は無音に -70.0 LUFS を返す。

    BGM のパスを間違えた・切り出しに失敗した場合にここへ落ちる。
    そのまま進むとゲイン計算が発散するので、測定の時点で止める。
    """
    stderr = ("  Integrated loudness:\n    I:         -70.0 LUFS\n"
              "  True peak:\n    Peak:      -inf dBFS\n")

    with pytest.raises(audio_mix.LoudnessUnreadable):
        parse_loudness(stderr)


# ---------------------------------------------------------------- 通し

def _tone(path, freq, seconds, volume=0.8):
    """実際のナレーション（約 -24 LUFS）と同じ水準の試験信号を作る。

    これより30 dB 静かい信号で試すと、18 LU 下に置いた BGM が ebur128 の
    測定下限（-70 LUFS）を割り、測定できずに落ちる。本番の素材では
    起きない条件なので、試験信号の側を実物に合わせる。
    """
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={freq}:duration={seconds}",
         "-filter:a", f"volume={volume}", str(path)],
        check=True, capture_output=True)
    return path


def test_書き出した音源で実際に分離比が保たれている(tmp_path):
    """plan した値ではなく、**ffmpeg が書き出したファイル**を測って確かめる。

    計画値どうしを比べると差は定義上いつも 18 LU になり、テストが
    何も検出しなくなる（フィルタの書き間違い・BGM の取り違え・
    ゲインの掛け忘れが全部すり抜ける）。
    """
    voice = _tone(tmp_path / "voice.wav", 300, 3)
    bgm = _tone(tmp_path / "bgm.wav", 800, 3)

    report = audio_mix.mix(voice, tmp_path / "mixed.wav", bgm_path=bgm)

    assert report.separation_lu >= MIN_SEPARATION_LU
    assert (tmp_path / "mixed.wav").exists()


def test_BGMがナレーションより短くても最後まで鳴る(tmp_path):
    """尺が足りない素材を渡しても、末尾が無音にならないこと。"""
    voice = _tone(tmp_path / "voice.wav", 300, 6)
    bgm = _tone(tmp_path / "bgm.wav", 800, 2)

    report = audio_mix.mix(voice, tmp_path / "mixed.wav", bgm_path=bgm)

    assert report.bed.integrated > -70.0
    assert report.separation_lu >= MIN_SEPARATION_LU


def test_最終ミックスは目標ラウドネスに寄る(tmp_path):
    voice = _tone(tmp_path / "voice.wav", 300, 4)
    bgm = _tone(tmp_path / "bgm.wav", 800, 4)

    report = audio_mix.mix(voice, tmp_path / "mixed.wav", bgm_path=bgm)

    assert report.final.integrated == pytest.approx(audio_mix.TARGET_LUFS,
                                                    abs=1.5)
    assert report.final.true_peak <= audio_mix.TARGET_TRUE_PEAK_DBFS + 0.5


def test_測定中のフレーム行ではなくサマリの値を読む():
    """ebur128 は測定中も `I:` を含む行を出す。先頭に一致してはいけない。

    t=0.5 秒時点の I は必ず -70.0（まだ何も測れていない）なので、
    stderr 全体を検索すると全音源が「無音」と判定される。
    """
    stderr = (
        "[Parsed_ebur128_0 @ 0000] t: 0.499988 M: -70.0 S: -120.7 "
        "I: -70.0 LUFS LRA: 0.0 LU\n"
        "[Parsed_ebur128_0 @ 0000] t: 0.999977 M: -22.1 S: -120.7 "
        "I: -22.1 LUFS LRA: 0.0 LU\n"
        "[Parsed_ebur128_0 @ 0000] Summary:\n"
        "\n"
        "  Integrated loudness:\n"
        "    I:         -24.5 LUFS\n"
        "    Threshold: -34.8 LUFS\n"
        "\n"
        "  True peak:\n"
        "    Peak:       -6.8 dBFS\n")

    got = parse_loudness(stderr)

    assert got.integrated == pytest.approx(-24.5)
