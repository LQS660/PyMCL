package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldColors
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.theme.LocalPclColors
import com.pymcl.mobile.data.t

/**
 * 账号 / Java / 设置 / 主题 / 反馈这几页共用的控件。
 *
 * 跟 `Screens.kt` 里那套（`CardBox` / `PrimaryBtn` / `FieldColors`）故意错开名字：
 * 那批归游戏域，这批归本域，各自改各自的不会撞车。颜色一律走
 * [LocalPclColors]，用户改主题色或切深色时这些控件跟着变，不用重启。
 */
object PyMclTheme {
    val Green = com.pymcl.mobile.theme.PclGreen
    val GreenDeep = com.pymcl.mobile.theme.PclGreenDeep
    val Background = com.pymcl.mobile.theme.PclBg
    val TextPrimary = com.pymcl.mobile.theme.PclText
}

@Composable
fun PclCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val c = LocalPclColors.current
    Column(
        modifier
            .fillMaxWidth()
            .border(1.dp, c.line, RoundedCornerShape(10.dp))
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        content = content,
    )
}

@Composable
fun PclSectionTitle(text: String, hint: String = "") {
    val c = LocalPclColors.current
    Text(text, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = c.text)
    if (hint.isNotBlank()) Text(hint, color = c.muted, fontSize = 12.sp)
}

@Composable
fun PclButton(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    val c = LocalPclColors.current
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = c.accent,
            disabledContainerColor = c.muted,
        ),
    ) { Text(text) }
}

@Composable
fun PclLink(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    val c = LocalPclColors.current
    TextButton(onClick = onClick, enabled = enabled) {
        Text(text, color = if (enabled) c.accent else c.muted, fontSize = 13.sp)
    }
}

@Composable
fun pclFieldColors(): TextFieldColors {
    val c = LocalPclColors.current
    return OutlinedTextFieldDefaults.colors(
        focusedBorderColor = c.accent,
        cursorColor = c.accent,
        focusedLabelColor = c.accent,
        unfocusedBorderColor = c.line,
        focusedTextColor = c.text,
        unfocusedTextColor = c.text,
    )
}

/** 一行文本设置。`secret=true` 时默认打码，右侧给一个「显示」。 */
@Composable
fun PclTextRow(
    label: String,
    value: String,
    hint: String = "",
    secret: Boolean = false,
    onChange: (String) -> Unit,
) {
    val c = LocalPclColors.current
    var reveal by rememberSaveable(label) { mutableStateOf(false) }
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        colors = pclFieldColors(),
        visualTransformation =
        if (!secret || reveal) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = if (!secret) null else {
            {
                TextButton(onClick = { reveal = !reveal }) {
                    Text(if (reveal) t("隐藏") else t("显示"), color = c.accent, fontSize = 12.sp)
                }
            }
        },
    )
    if (hint.isNotBlank()) Text(hint, color = c.muted, fontSize = 11.sp)
}

@Composable
fun PclSwitchRow(label: String, checked: Boolean, hint: String = "", onChange: (Boolean) -> Unit) {
    val c = LocalPclColors.current
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(label, fontSize = 14.sp, color = c.text)
            if (hint.isNotBlank()) Text(hint, color = c.muted, fontSize = 11.sp)
        }
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(checkedTrackColor = c.accent),
        )
    }
}

@Composable
fun PclSliderRow(
    label: String,
    value: Int,
    range: IntRange,
    suffix: String = "",
    onChange: (Int) -> Unit,
    onCommit: () -> Unit = {},
) {
    val c = LocalPclColors.current
    Text("$label $value$suffix", color = c.muted, fontSize = 12.sp)
    Slider(
        value = value.toFloat(),
        onValueChange = { onChange(it.toInt()) },
        onValueChangeFinished = onCommit,
        valueRange = range.first.toFloat()..range.last.toFloat(),
        colors = SliderDefaults.colors(thumbColor = c.accent, activeTrackColor = c.accent),
    )
}

/** 一排可横滑的选项，用来顶掉桌面那些下拉框。 */
@Composable
fun PclOptionRow(
    label: String,
    options: List<Pair<String, String>>,
    selected: String,
    onPick: (String) -> Unit,
) {
    val c = LocalPclColors.current
    if (label.isNotBlank()) Text(label, color = c.muted, fontSize = 12.sp)
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        options.forEach { (key, text) ->
            val on = key == selected
            Text(
                text,
                modifier = Modifier
                    .background(if (on) c.hover else Color.Transparent, RoundedCornerShape(8.dp))
                    .clickable { onPick(key) }
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                color = if (on) c.accent else c.text,
                fontSize = 13.sp,
                maxLines = 1,
            )
        }
    }
}

/** 账号 / Java 列表上那个圆角小方块，省掉一次网络头像请求。 */
@Composable
fun PclTile(text: String, tint: Color, size: Int = 36) {
    Column(
        Modifier
            .height(size.dp)
            .background(tint.copy(alpha = 0.16f), RoundedCornerShape(8.dp))
            .padding(horizontal = (size / 4).dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text.take(1).uppercase(),
            color = tint,
            fontWeight = FontWeight.Bold,
            fontSize = (size / 2).sp,
        )
    }
}

@Composable
fun PclPill(text: String, tint: Color) {
    Text(
        text,
        modifier = Modifier
            .background(tint.copy(alpha = 0.14f), RoundedCornerShape(6.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
        color = tint,
        fontSize = 11.sp,
        maxLines = 1,
    )
}

@Composable
fun PclEmpty(text: String) {
    val c = LocalPclColors.current
    Text(text, color = c.muted, fontSize = 13.sp)
}

/** 成功 / 失败那一行反馈。空串就整行不占位。 */
@Composable
fun PclNotice(text: String, error: Boolean = false) {
    if (text.isBlank()) return
    val c = LocalPclColors.current
    Text(
        text,
        color = if (error) com.pymcl.mobile.theme.PclDanger else c.accent,
        fontSize = 12.sp,
        maxLines = 4,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
fun PclGap(height: Int = 6) {
    Spacer(Modifier.height(height.dp))
}

/** 只读键值行，给「本机配置预览」这类展示用。 */
@Composable
fun PclKeyValue(key: String, value: String) {
    val c = LocalPclColors.current
    Row(Modifier.fillMaxWidth()) {
        Text(key, color = c.muted, fontSize = 12.sp, modifier = Modifier.weight(0.4f))
        Text(
            value,
            color = c.text,
            fontSize = 12.sp,
            modifier = Modifier.weight(0.6f),
            maxLines = 3,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/** 记住一个可撤销的提示条：新消息覆盖旧的，不堆叠。 */
@Composable
fun rememberNotice(): NoticeState = remember { NoticeState() }

class NoticeState {
    var text by mutableStateOf("")
        private set
    var isError by mutableStateOf(false)
        private set

    fun ok(message: String) {
        text = message
        isError = false
    }

    fun fail(message: String) {
        text = message
        isError = true
    }

    fun clear() {
        text = ""
        isError = false
    }
}
