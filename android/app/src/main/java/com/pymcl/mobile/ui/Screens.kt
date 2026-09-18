package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextFieldColors
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclHover
import com.pymcl.mobile.theme.PclLine
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.theme.PclText
import com.pymcl.mobile.vm.AppViewModel
import com.pymcl.mobile.data.t

/** 页面之间共用的那几块积木，各个 Screen 都从这里取，样式只在这里改一处。 */

val ErrorRed = Color(0xFFC62828)

@Composable
fun CardBox(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .border(1.dp, PclLine, RoundedCornerShape(10.dp))
            .padding(14.dp),
        content = content,
    )
}

@Composable
fun PrimaryBtn(text: String, enabled: Boolean = true, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = PclGreen,
            disabledContainerColor = PclMuted,
        ),
    ) { Text(text) }
}

@Composable
fun FieldColors(): TextFieldColors = OutlinedTextFieldDefaults.colors(
    focusedBorderColor = PclGreen,
    cursorColor = PclGreen,
    focusedLabelColor = PclGreen,
)

@Composable
fun SectionHeader(title: String, subtitle: String = "", action: (@Composable () -> Unit)? = null) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, color = PclText)
            if (subtitle.isNotBlank()) {
                Text(subtitle, color = PclMuted, fontSize = 12.sp)
            }
        }
        action?.invoke()
    }
}

@Composable
fun EmptyHint(text: String, modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(text, color = PclMuted, fontSize = 13.sp)
    }
}

@Composable
fun Pill(text: String, color: Color = PclGreen) {
    Text(
        text,
        modifier = Modifier
            .background(PclHover, RoundedCornerShape(8.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
        color = color,
        fontSize = 11.sp,
        maxLines = 1,
    )
}

/**
 * 横向筹码条。[limit] 之外的不渲染：版本列表动辄上千条，
 * 一次性铺进 `horizontalScroll` 会把整行的测量成本拉满。
 */
@Composable
fun ChipRow(
    label: String,
    items: List<String>,
    selected: String,
    limit: Int = 12,
    onPick: (String) -> Unit,
) {
    if (label.isNotBlank()) Text(label, color = PclMuted, fontSize = 12.sp)
    Row(
        Modifier
            .fillMaxWidth()
            .horizontalScroll(rememberScrollState())
            .padding(bottom = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (items.isEmpty()) {
            Text(t("无"), color = PclMuted, fontSize = 12.sp)
            return@Row
        }
        items.take(limit).forEach { item ->
            val on = item == selected
            Text(
                item,
                modifier = Modifier
                    .background(if (on) PclHover else Color.Transparent, RoundedCornerShape(8.dp))
                    .clickable { onPick(item) }
                    .padding(horizontal = 10.dp, vertical = 6.dp),
                color = if (on) PclGreen else PclText,
                fontSize = 13.sp,
                maxLines = 1,
            )
        }
    }
}

@Composable
fun SearchRow(
    value: String,
    label: String,
    actionText: String,
    actionEnabled: Boolean = true,
    onValueChange: (String) -> Unit,
    onAction: () -> Unit,
) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            label = { Text(label) },
            modifier = Modifier.weight(1f),
            singleLine = true,
            colors = FieldColors(),
        )
        Spacer(Modifier.width(8.dp))
        PrimaryBtn(actionText, enabled = actionEnabled, onClick = onAction)
    }
}

/** 顶部那条进度：只有真的在忙时才占位，免得每个页面都空着一条灰线。 */
@Composable
fun BusyBar(vm: AppViewModel) {
    if (!vm.busy && vm.progress <= 0) return
    Column(Modifier.fillMaxWidth()) {
        LinearProgressIndicator(
            progress = { (vm.progress / 100f).coerceIn(0f, 1f) },
            modifier = Modifier.fillMaxWidth(),
            color = PclGreen,
        )
        Spacer(Modifier.height(4.dp))
        Text(vm.status, color = PclMuted, fontSize = 12.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun ErrorLine(vm: AppViewModel) {
    val message = vm.error ?: return
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(message, color = ErrorRed, fontSize = 12.sp, modifier = Modifier.weight(1f))
        TextButton(onClick = { vm.error = null }) { Text(t("知道了"), color = PclGreen) }
    }
}
